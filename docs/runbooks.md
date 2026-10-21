# Local operational runbooks

## Events accepted but no incidents appear

1. Open Pipeline health; check pending jobs and dead letters. API health checks do not establish worker health.
2. Confirm the worker is running (`make dev` starts it with the API and frontend).
3. Inspect worker stderr. Logged failures show the job ID and exception class, not raw event data.
4. Use an admin token with `GET /api/v1/dlq`. Unsupported parser formats require a parser fix before replay.
5. Verify that the supplied timestamps, environment, host, service and source group actually meet a rule threshold. Benign events should not generate alerts.

## Dead-letter repair

Fix the parser/rule, run the relevant tests, restart the worker, then `POST /api/v1/dlq/{job_id}/replay` as an administrator. Original redacted payloads remain in the database. The endpoint resets attempts and requeues the job; unchanged invalid data will fail again. Replay actions are audited.

## Worker outage exercise

Run API, worker and frontend separately instead of the supervisor. Stop only the worker, ingest a batch, and observe pending jobs increase. Restart the worker and verify that pending work drains. Redis delivery recovery waits at least 30 seconds before reclaiming a stale message. Re-delivery of the same event ID must not add a second event or duplicate detections.

## Redis outage / permanent broker data loss

Previously accepted jobs remain durable. Redis-backed rate limiting rejects new intake with `503` while Redis is unavailable. Restore connectivity to resume intake and dispatch. Do not delete volumes as a repair step.

If the Redis stream is lost, the dispatcher automatically requeues published jobs whose publication is older than 60 seconds. Stable event IDs protect against duplicate effects. `scripts/failure_drill.py` exercises this reconciliation against the local stack. Do not manually reset job state unless investigating a condition the automatic recovery cannot handle.

## Local SQLite backup and restore drill

Stop the supervised processes before swapping databases. For a consistent online backup, use SQLite's backup API (copying only `sentinel.db` while WAL is active can lose committed data):

```sh
.venv/bin/python - <<'PY'
import sqlite3
with sqlite3.connect('sentinel.db') as source, sqlite3.connect('sentinel-backup.db') as target:
    source.backup(target)
print('Created a consistent local backup.')
PY
```

To test restore, stop services, preserve the original database and any WAL/SHM files, and use the backup at a separate path via `DATABASE_URL=sqlite:///./restored.db`. Verify event, alert, incident, note and audit counts before changing the primary database. Do not overwrite the only copy. For Compose PostgreSQL, `make backup-restore` creates a private dump and restores into a separate temporary database, compares counts, then removes only that temporary database. `make search-restore` snapshots local OpenSearch and verifies restoration under temporary index names. Run with ingestion quiet. Managed AWS restore testing remains outside local verification.

## Access and secret changes

Changing `ADMIN_PASSWORD` after initial setup does not overwrite an existing user's stored password. The bootstrap only creates a missing admin. Administrators can reset/disable users through `PATCH /api/v1/users/{username}`; updates revoke their sessions. Logout revokes a refresh-token family. Refresh-token reuse revokes the family too. Rotating `JWT_SECRET` invalidates all outstanding tokens immediately. Rotating `COLLECTOR_KEY` requires updating every collector. Restart processes after changing environment configuration.

## Excessive false positives

Preserve examples of benign and suspicious events. Add regression fixtures, then adjust the YAML conditions/thresholds in a reviewed change. Restart the worker to load changes. Do not assume that a technique mapping proves malicious activity. Verify both precision and missed-detection behavior on representative data.

## Prometheus

`GET /metrics` requires `X-API-Key`. It exports gauges for stored events/alerts, open incidents, queue depth and dead letters. Compose provisions Prometheus, a key-injecting internal metrics proxy, alert rules, and Grafana at `http://127.0.0.1:3100`. Worker heartbeat age and exhausted integration tasks are also exposed. Alert rules have no external notification destination configured. Do not expose metrics publicly or commit collector keys into scrape configuration.

## Integration failures and retention

Open Administration → Integration deliveries to inspect/replay dead or disabled tasks. Configure the intended provider before replay; AI and outbound delivery default to disabled. Providers retry independently of detection. See `docs/integrations.md` for setup and delivery semantics.

The maintenance worker runs retention hourly. Configure `EVENT_RETENTION_DAYS` and `JOB_RETENTION_DAYS`; incident-linked relational evidence is preserved. `scripts/maintenance.py retention` runs it explicitly, and `search-backfill` queues reindexing. Both use the selected database configuration: a host-native invocation defaults to SQLite, not the Compose PostgreSQL database. Run inside the API container when maintaining Compose data.

## Complete local outage drill

With Compose running and no active analyst session, run `.venv/bin/python scripts/failure_drill.py`. It stops/restarts only this project's search/Redis/PostgreSQL/worker services, verifies fallback and durable recovery, and restores stopped services in `finally` blocks. No AWS or external notification endpoint is contacted.
