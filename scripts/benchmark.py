"""Measure local intake and end-to-end drain; never targets an arbitrary remote host."""

import argparse
import json
import time
from datetime import datetime, timezone
from uuid import uuid4
import httpx
from sentinel.config import Settings

parser = argparse.ArgumentParser()
parser.add_argument("--events", type=int, default=200, choices=range(1, 5001), metavar="1..5000")
args = parser.parse_args()
s = Settings()
run = uuid4().hex
with httpx.Client(base_url="http://127.0.0.1:8180", timeout=30) as client:
    login = client.post(
        "/api/v1/auth/login", json={"username": s.admin_username, "password": s.admin_password}
    )
    login.raise_for_status()
    client.headers["Authorization"] = "Bearer " + login.json()["access_token"]
    before = client.get("/api/v1/dashboard").json()["events"]
    latencies = []
    start = time.perf_counter()
    for i in range(0, args.events, 200):
        payload = [
            {
                "event_id": str(uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "environment": "local",
                "source_type": "application",
                "host": "benchmark",
                "service": "benchmark-" + run,
                "event_type": "heartbeat",
                "message": "Benign load-test heartbeat",
                "source_ip": "192.0.2.99",
            }
            for _ in range(min(200, args.events - i))
        ]
        batch = time.perf_counter()
        client.post(
            "/api/v1/events", headers={"X-API-Key": s.collector_key}, json={"events": payload}
        ).raise_for_status()
        latencies.append(time.perf_counter() - batch)
    accepted = time.perf_counter() - start
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if client.get("/api/v1/dashboard").json()["events"] >= before + args.events:
            break
        time.sleep(0.5)
    else:
        raise SystemExit("Drain exceeded 180 seconds; inspect backlog before retrying.")
    print(
        json.dumps(
            {
                "events": args.events,
                "ingestion_seconds": round(accepted, 3),
                "accepted_eps": round(args.events / accepted, 2),
                "batch_p95_seconds": round(sorted(latencies)[int((len(latencies) - 1) * 0.95)], 3),
                "end_to_end_seconds": round(time.perf_counter() - start, 3),
                "scope": "local burst, not sustained capacity",
            }
        )
    )
