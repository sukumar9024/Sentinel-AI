"""Durable pipeline dispatcher. Database locks protect shared detection state."""

import logging
import os
import socket
import time
from datetime import timedelta

from redis import Redis
from redis.exceptions import ResponseError
from sqlalchemy import or_, select

from .config import Settings
from .engine import load_rules, process_job
from .locking import pipeline_transaction
from .models import Heartbeat, Job, JobSchedule, database, now

log = logging.getLogger("sentinel.worker")
STREAM = "security.raw.events"
GROUP = "pipeline"


def heartbeat(factory, name, detail=None):
    with factory.begin() as session:
        row = session.get(Heartbeat, name)
        if row:
            row.seen_at, row.detail = now(), detail or {}
        else:
            session.add(Heartbeat(name=name, detail=detail or {}))


def execute(factory, job_id, rules):
    try:
        with pipeline_transaction(factory) as session:
            process_job(session, job_id, rules)
        return True
    except Exception as error:
        with pipeline_transaction(factory) as session:
            job = session.get(Job, job_id)
            if job and job.state not in {"done", "dead"}:
                job.attempts += 1
                job.error = type(error).__name__
                job.state = "dead" if job.attempts >= 3 else "queued"
                schedule = session.get(JobSchedule, job_id)
                if not schedule:
                    schedule = JobSchedule(job_id=job_id)
                    session.add(schedule)
                schedule.due_at = now() + timedelta(seconds=2**job.attempts)
        log.warning("Job %s failed (%s)", job_id, type(error).__name__)
        return False


def tick(factory, rules, broker=None, consumer="pipeline"):
    if broker:
        try:
            broker.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except ResponseError as error:
            if "BUSYGROUP" not in str(error):
                raise
    with pipeline_transaction(factory) as session:
        # Recover durable outbox rows even after complete Redis data loss.
        stale = session.scalars(
            select(Job)
            .join(JobSchedule, Job.id == JobSchedule.job_id)
            .where(Job.state == "published", JobSchedule.published_at < now() - timedelta(seconds=60))
        ).all()
        for job in stale:
            job.state = "queued"
        jobs = session.scalars(
            select(Job)
            .outerjoin(JobSchedule, Job.id == JobSchedule.job_id)
            .where(Job.state == "queued", or_(JobSchedule.job_id.is_(None), JobSchedule.due_at <= now()))
            .order_by(Job.created_at, Job.id)
            .limit(100)
        ).all()
        ids = [j.id for j in jobs]
        if broker:
            for job in jobs:
                broker.xadd(STREAM, {"job_id": job.id})
                job.state = "published"
                schedule = session.get(JobSchedule, job.id)
                if not schedule:
                    schedule = JobSchedule(job_id=job.id)
                    session.add(schedule)
                schedule.published_at = now()
    if not broker:
        for job_id in ids:
            execute(factory, job_id, rules)
        return len(ids)
    _, recovered, *_ = broker.xautoclaim(STREAM, GROUP, consumer, 30000, "0-0", count=100)
    fresh = broker.xreadgroup(GROUP, consumer, {STREAM: ">"}, count=100, block=1000)
    messages = recovered + [entry for _, entries in fresh for entry in entries]
    for message_id, fields in messages:
        execute(factory, fields["job_id"], rules)
        broker.xack(STREAM, GROUP, message_id)
        broker.xdel(STREAM, message_id)
    return len(messages)


def run():
    settings = Settings()
    factory = database(settings.database_url)
    rules = load_rules(settings.rules_path)
    broker = (
        Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=5, socket_connect_timeout=5)
        if settings.redis_url
        else None
    )
    name = f"pipeline:{socket.gethostname()}:{os.getpid()}"
    logging.basicConfig(level=logging.INFO)
    last_beat = 0
    while True:
        try:
            count = tick(factory, rules, broker, name)
            if time.monotonic() - last_beat > 5:
                heartbeat(factory, name, {"processed_last_batch": count})
                last_beat = time.monotonic()
            if not broker:
                time.sleep(0.25)
        except Exception as error:
            log.warning("Pipeline dependency unavailable (%s)", type(error).__name__)
            time.sleep(2)


if __name__ == "__main__":
    run()
