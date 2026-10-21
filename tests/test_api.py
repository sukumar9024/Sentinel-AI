import json

from sqlalchemy import select

from sentinel.models import Audit, Job
from sentinel.schema import redact
from test_pipeline import event, process
from sentinel.lab import scenario


def test_auth_and_collector_boundaries(client, headers):
    assert client.get("/api/v1/incidents").status_code == 401
    assert client.post("/api/v1/events", json={"events": [event()]}).status_code == 401
    assert (
        client.post(
            "/api/v1/events", json={"events": [event()]}, headers={"X-API-Key": "collector-test-" * 4}
        ).status_code
        == 202
    )
    assert client.get("/api/v1/incidents", headers=headers).status_code == 200
    assert client.get("/metrics").status_code == 401
    assert client.get("/metrics", headers={"X-API-Key": "collector-test-" * 4}).status_code == 200


def test_validation_payload_boundaries(client):
    auth = {"X-API-Key": "collector-test-" * 4}
    invalid = event()
    invalid["timestamp"] = "not-a-time"
    assert client.post("/api/v1/events", json={"events": [invalid]}, headers=auth).status_code == 422
    assert client.post("/api/v1/events", content="x" * 524289, headers=auth).status_code == 413
    invalid["timestamp"] = "2025-01-01T00:00:00"
    assert client.post("/api/v1/events", json={"events": [invalid]}, headers=auth).status_code == 422


def test_viewer_cannot_mutate(client, headers):
    response = client.post(
        "/api/v1/users",
        json={"username": "viewer", "password": "viewer-password-123", "role": "viewer"},
        headers=headers,
    )
    assert response.status_code == 201
    token = client.post(
        "/api/v1/auth/login", json={"username": "viewer", "password": "viewer-password-123"}
    ).json()["access_token"]
    viewer = {"Authorization": "Bearer " + token}
    assert client.get("/api/v1/incidents", headers=viewer).status_code == 200
    assert (
        client.patch("/api/v1/incidents/missing", json={"status": "RESOLVED"}, headers=viewer).status_code
        == 403
    )
    assert client.post("/api/v1/lab/run", headers=viewer).status_code == 403
    assert client.get("/api/v1/dlq", headers=viewer).status_code == 403
    assert client.get("/api/v1/audit", headers=viewer).status_code == 403


def test_lifecycle_notes_and_audit(app, client, headers):
    for payload in scenario():
        process(app, payload)
    incident_id = client.get("/api/v1/incidents", headers=headers).json()["items"][0]["id"]
    assert (
        client.patch(
            "/api/v1/incidents/" + incident_id, json={"status": "RESOLVED"}, headers=headers
        ).status_code
        == 422
    )
    assert (
        client.patch(
            "/api/v1/incidents/" + incident_id,
            json={"status": "INVESTIGATING", "owner": "admin"},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/incidents/" + incident_id + "/notes",
            json={"body": "Validated this is a synthetic lab scenario."},
            headers=headers,
        ).status_code
        == 201
    )
    assert (
        client.patch(
            "/api/v1/incidents/" + incident_id,
            json={"status": "RESOLVED", "resolution": "Synthetic lab, no compromise."},
            headers=headers,
        ).status_code
        == 200
    )
    detail = client.get("/api/v1/incidents/" + incident_id, headers=headers).json()
    assert detail["status"] == "RESOLVED"
    assert len(detail["notes"]) == 1
    assert detail["evidence_count"] == 33
    for missing_resolution in (None, "", "   "):
        assert (
            client.patch(
                "/api/v1/incidents/" + incident_id, json={"resolution": missing_resolution}, headers=headers
            ).status_code
            == 422
        )
    with app.state.factory() as session:
        assert len(session.scalars(select(Audit).where(Audit.target == incident_id)).all()) == 3


def test_redaction_before_persistence(app, client):
    payload = event(message="password=hunter2 token=abc123")
    payload["attributes"] = {"Authorization": "Bearer xyz", "nested": {"api_key": "private"}}
    client.post("/api/v1/events", json={"events": [payload]}, headers={"X-API-Key": "collector-test-" * 4})
    with app.state.factory() as session:
        stored = json.dumps(session.scalar(select(Job)).payload)
        for secret in ["hunter2", "abc123", "Bearer xyz", "private"]:
            assert secret not in stored
    assert redact({"cookie": "SESSION=abc"}) == {"cookie": "[REDACTED]"}


def test_login_rate_limit(client):
    for _ in range(10):
        assert (
            client.post("/api/v1/auth/login", json={"username": "nope", "password": "invalid"}).status_code
            == 401
        )
    assert (
        client.post("/api/v1/auth/login", json={"username": "nope", "password": "invalid"}).status_code == 429
    )


def test_paginated_event_search(app, client, headers):
    for payload in scenario():
        process(app, payload)
    response = client.get(
        "/api/v1/events?event_type=authentication_failure&limit=10&offset=10", headers=headers
    ).json()
    assert response["total"] == 25
    assert len(response["items"]) == 10


def test_oversized_event_and_batch_rejected(client):
    auth = {"X-API-Key": "collector-test-" * 4}
    payload = event(attributes={"large": "a" * 17000})
    assert client.post("/api/v1/events", json={"events": [payload]}, headers=auth).status_code == 422
    assert client.post("/api/v1/events", json={"events": [event()] * 201}, headers=auth).status_code == 422


def test_rate_limit_is_thread_safe():
    from concurrent.futures import ThreadPoolExecutor
    from sentinel.security import RateLimiter

    limiter = RateLimiter()
    with ThreadPoolExecutor(max_workers=20) as pool:
        accepted = list(pool.map(lambda _: limiter.allow("same-source", 10), range(100)))
    assert sum(accepted) == 10
