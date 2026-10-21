"""Independent integrations worker: provider failures never roll back detection."""

import logging
import os
import socket
import time
from datetime import timedelta

from sqlalchemy import or_, select
from .config import Settings
from .integrations import Disabled, analyze, index_event, install_search_template, notify
from .locking import pipeline_transaction
from .models import Event, Incident, Task, database, now, serialize, uid
from .worker import heartbeat

log = logging.getLogger("sentinel.integrations")


def claim(factory):
    with pipeline_transaction(factory) as session:
        task = session.scalar(
            select(Task)
            .where(
                or_(
                    (Task.state == "queued") & (Task.due_at <= now()),
                    (Task.state == "running") & (Task.lease_until < now()),
                )
            )
            .order_by(Task.due_at, Task.created_at)
            .limit(1)
        )
        if not task:
            return None
        task.state, task.lease_token = "running", uid()
        task.lease_until = now() + timedelta(minutes=5)
        return serialize(task)


def tick(factory, settings):
    task = claim(factory)
    if not task:
        return False
    result, status, error = None, "done", None
    try:
        if task["kind"] == "search":
            with factory() as session:
                event = session.get(Event, task["target"])
                data = event.data if event else None
            if data:
                index_event(settings, data)
        elif task["kind"] == "ai":
            result = analyze(factory, settings, task["target"])
        else:
            with factory() as session:
                incident = session.get(Incident, task["payload"]["incident_id"])
                data = serialize(incident)
                data["severity"] = task["payload"]["severity"]
            notify(settings, task["kind"], task["id"], data)
    except Disabled:
        status = "disabled"
    except Exception as exc:
        error = type(exc).__name__
        status = "dead" if task["attempts"] >= 4 else "queued"
        log.warning("Integration %s failed (%s)", task["kind"], error)
    with pipeline_transaction(factory) as session:
        row = session.get(Task, task["id"])
        if row.lease_token != task["lease_token"]:
            return True
        if row.generation != task["generation"]:
            row.state = "queued"
            return True
        row.state, row.error = status, error
        if error:
            row.attempts += 1
            row.due_at = now() + timedelta(seconds=min(300, 2**row.attempts))
        else:
            row.completed_at = now()
        if result:
            incident = session.get(Incident, task["target"])
            incident.analysis = result
    return True


def run():
    settings = Settings()
    factory = database(settings.database_url)
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    name = f"integrations:{socket.gethostname()}:{os.getpid()}"
    template_ready, last_beat = False, 0
    while True:
        try:
            if not template_ready:
                try:
                    install_search_template(settings)
                    template_ready = True
                except Exception as error:
                    log.warning("Search template pending (%s)", type(error).__name__)
            if time.monotonic() - last_beat > 5:
                heartbeat(factory, name)
                last_beat = time.monotonic()
            if not tick(factory, settings):
                time.sleep(0.5)
        except Exception as error:
            log.warning("Integration dependency unavailable (%s)", type(error).__name__)
            time.sleep(2)


if __name__ == "__main__":
    run()
