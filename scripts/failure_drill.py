"""Local-only outage/recovery checks. Touches only this repository's Compose services."""

import json
from datetime import datetime, timezone
from uuid import uuid4

import httpx
from sentinel.config import Settings
from compose_smoke import compose, wait_for


def main():
    settings = Settings()
    with httpx.Client(base_url="http://127.0.0.1:8180", timeout=10) as client:
        response = client.post(
            "/api/v1/auth/login",
            json={"username": settings.admin_username, "password": settings.admin_password},
        )
        response.raise_for_status()
        client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
        before = client.get("/api/v1/dashboard").json()["events"]
        compose("stop", "opensearch")
        try:
            event = {
                "event_id": str(uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "environment": "local",
                "source_type": "application",
                "host": "failure-drill",
                "service": "failure-drill",
                "event_type": "privileged_user_created",
                "message": "Synthetic provider outage drill",
                "source_ip": "192.0.2.88",
            }
            client.post(
                "/api/v1/events", headers={"X-API-Key": settings.collector_key}, json={"events": [event]}
            ).raise_for_status()
            wait_for(
                lambda: client.get("/api/v1/dashboard").json()["events"] >= before + 1,
                "detection during search outage",
            )
            assert client.get("/api/v1/search?q=failure-drill").json()["backend"] == "database-fallback"
        finally:
            compose("start", "opensearch")
        wait_for(
            lambda: client.get("/api/v1/search?service=failure-drill").json().get("backend") == "opensearch",
            "search recovery",
            120,
        )
        # Redis outage fails intake closed (shared rate limiter), rather than falsely acknowledging work.
        compose("stop", "redis")
        try:
            rejected = client.post(
                "/api/v1/events", headers={"X-API-Key": settings.collector_key}, json={"events": [event]}
            )
            assert rejected.status_code == 503
        finally:
            compose("start", "redis")
        wait_for(lambda: client.get("/healthz").status_code == 200, "api readiness")
        # Restart persistence without deleting any volume.
        compose("restart", "postgres")
        wait_for(lambda: client.get("/healthz").status_code == 200, "database restart")
        assert client.get("/api/v1/dashboard").json()["events"] >= before + 1
        # Simulate permanent loss of this platform's Redis stream while keeping the outbox.
        compose("stop", "worker")
        try:
            recovery_event = dict(event, event_id=str(uuid4()), message="Synthetic broker loss drill")
            accepted = client.post(
                "/api/v1/events",
                headers={"X-API-Key": settings.collector_key},
                json={"events": [recovery_event]},
            )
            accepted.raise_for_status()
            job_id = accepted.json()["job_ids"][0]
            code = """
from datetime import timedelta
from redis import Redis
from sentinel.config import Settings
from sentinel.models import Job,JobSchedule,database,now
s=Settings()
with database(s.database_url).begin() as db:
    job=db.get(Job,JOB_ID)
    job.state='published'
    db.add(JobSchedule(job_id=JOB_ID,published_at=now()-timedelta(seconds=120)))
Redis.from_url(s.redis_url).delete('security.raw.events')
""".replace("JOB_ID", repr(job_id))
            compose("exec", "-T", "api", "python", "-c", code)
        finally:
            compose("start", "worker")
        wait_for(lambda: client.get("/api/v1/dashboard").json()["queued"] == 0, "outbox reconciliation", 90)
        assert client.get("/api/v1/dashboard").json()["events"] >= before + 2
        print(
            json.dumps(
                {
                    "search_outage_fallback": "passed",
                    "redis_fail_closed": "passed",
                    "postgres_restart": "passed",
                    "broker_loss_reconciliation": "passed",
                }
            )
        )


if __name__ == "__main__":
    main()
