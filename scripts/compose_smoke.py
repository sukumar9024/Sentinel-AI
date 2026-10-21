"""Exercise the local Compose stack only. Never invokes AWS or external notification endpoints."""

import json
import subprocess
import time

import httpx
from sentinel.config import Settings


def compose(*args):
    return subprocess.run(
        ["docker", "compose", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def wait_for(predicate, description, seconds=60):
    until = time.monotonic() + seconds
    while time.monotonic() < until:
        result = predicate()
        if result:
            return result
        time.sleep(1)
    raise AssertionError("Timed out: " + description)


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
        compose(
            "exec",
            "-T",
            "sample-app",
            "python",
            "-c",
            "import urllib.request; urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:8001/scenario',method='POST'))",
        )
        wait_for(
            lambda: client.get("/api/v1/dashboard").json()["events"] >= before + 33, "collector pipeline"
        )
        wait_for(
            lambda: (
                client.get("/api/v1/search?service=collected-identity").json().get("backend") == "opensearch"
            ),
            "OpenSearch query",
        )
        incidents = client.get("/api/v1/incidents?q=collected-identity").json()["items"]
        assert any(i["severity"] == "critical" for i in incidents)
        # Queued work survives stopping just this project's detection worker.
        compose("stop", "worker")
        try:
            from sentinel.lab import scenario

            batch = scenario()
            before = client.get("/api/v1/dashboard").json()["events"]
            accepted = client.post(
                "/api/v1/events", headers={"X-API-Key": settings.collector_key}, json={"events": batch}
            )
            accepted.raise_for_status()
            assert client.get("/api/v1/dashboard").json()["queued"] >= 33
        finally:
            compose("start", "worker")
        wait_for(
            lambda: client.get("/api/v1/dashboard").json()["events"] >= before + 33, "worker restart drain"
        )
        # Prove replay idempotency through the actual Redis/PostgreSQL path.
        client.post(
            "/api/v1/events", headers={"X-API-Key": settings.collector_key}, json={"events": batch}
        ).raise_for_status()
        wait_for(lambda: client.get("/api/v1/dashboard").json()["queued"] == 0, "duplicate replay drain")
        assert client.get("/api/v1/dashboard").json()["events"] == before + 33
        print(
            json.dumps(
                {
                    "collector": "passed",
                    "opensearch": "passed",
                    "correlation": "passed",
                    "worker_restart": "passed",
                    "duplicate_replay": "passed",
                }
            )
        )


if __name__ == "__main__":
    main()
