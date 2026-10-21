"""Explicit retention/backfill tooling; no cloud calls unless an AWS endpoint was configured."""

import argparse
from sqlalchemy import select
from sentinel.config import Settings
from sentinel.models import Event, Task, database, now
from sentinel.integrations import retention
from sentinel.outbox import schedule

parser = argparse.ArgumentParser()
parser.add_argument("action", choices=["retention", "search-backfill"])
args = parser.parse_args()
settings = Settings()
factory = database(settings.database_url)
if args.action == "retention":
    print({"removed_unlinked_events": retention(factory, settings)})
else:
    with factory.begin() as session:
        for event_id in session.scalars(select(Event.id)).yield_per(200):
            schedule(session, "search", event_id)
        for task in session.scalars(
            select(Task).where(Task.kind == "search", Task.state.in_(["dead", "disabled", "done"]))
        ):
            task.state, task.attempts, task.due_at = "queued", 0, now()
    print("Search backfill queued; run the integrations worker to deliver it.")
