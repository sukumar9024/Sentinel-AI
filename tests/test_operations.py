from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import func, select

from sentinel import integration_worker
from sentinel.models import Alert, Event, Incident, Job, Task, now
from sentinel.worker import execute, tick
from sentinel.engine import load_rules
from sentinel.lab import scenario
from test_pipeline import event, process


def test_refresh_rotation_logout_and_reuse_revokes_family(app, client):
    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
    ).json()
    rotated = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}).json()
    old = {"Authorization": "Bearer " + login["access_token"]}
    new = {"Authorization": "Bearer " + rotated["access_token"]}
    assert client.get("/api/v1/auth/me", headers=old).status_code == 401
    assert client.get("/api/v1/auth/me", headers=new).status_code == 200
    assert (
        client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]}).status_code == 401
    )
    assert client.get("/api/v1/auth/me", headers=new).status_code == 401
    login = client.post(
        "/api/v1/auth/login", json={"username": "admin", "password": "test-admin-password"}
    ).json()
    headers = {"Authorization": "Bearer " + login["access_token"]}
    assert client.post("/api/v1/auth/logout", headers=headers).status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers).status_code == 401


def test_disable_user_invalidates_access(client, headers):
    client.post(
        "/api/v1/users",
        headers=headers,
        json={"username": "analyst", "password": "long-password-here", "role": "analyst"},
    )
    token = client.post(
        "/api/v1/auth/login", json={"username": "analyst", "password": "long-password-here"}
    ).json()["access_token"]
    assert client.patch("/api/v1/users/analyst", headers=headers, json={"enabled": False}).status_code == 200
    assert client.get("/api/v1/incidents", headers={"Authorization": "Bearer " + token}).status_code == 401
    assert client.patch("/api/v1/users/admin", headers=headers, json={"enabled": False}).status_code == 422


def test_rule_toggle_and_critical_asset_scoring(app, client, headers):
    rule = load_rules("rules/detections.yaml")[0]
    assert client.patch("/api/v1/rules/AUTH-001", headers=headers, json={"enabled": False}).status_code == 200
    for i in range(10):
        process(app, event(i, event_type="authentication_failure"), [rule])
    with app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(Alert)) == 0
    client.patch("/api/v1/rules/AUTH-001", headers=headers, json={"enabled": True})
    assert (
        client.post(
            "/api/v1/assets",
            headers=headers,
            json={
                "host": "host-1",
                "service": "auth",
                "environment": "local",
                "owner": "security",
                "criticality": "critical",
            },
        ).status_code
        == 201
    )
    process(app, event(11, event_type="authentication_failure"), [rule])
    with app.state.factory() as session:
        assert session.scalar(select(Incident)).severity == "critical"


def test_collector_retry_ids_are_stable(app, client):
    payload = event(event_type="heartbeat")
    payload.pop("event_id")
    auth = {"X-API-Key": "collector-test-" * 4}
    for _ in range(2):
        assert client.post("/api/v1/collectors/fluent-bit", headers=auth, json=[payload]).status_code == 202
    tick(app.state.factory, load_rules("rules/detections.yaml"))
    with app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(Event)) == 1


def test_expired_integration_lease_reclaimed(app):
    with app.state.factory.begin() as session:
        session.add(
            Task(
                id="expired",
                kind="search",
                target="missing",
                state="running",
                lease_until=now() - timedelta(seconds=1),
            )
        )
    task = integration_worker.claim(app.state.factory)
    assert task["id"] == "expired"
    assert task["lease_token"]


def test_ai_failure_does_not_break_incident(app, monkeypatch):
    for payload in scenario():
        process(app, payload)
    with app.state.factory.begin() as session:
        ai = session.scalar(select(Task).where(Task.kind == "ai"))
        ai.due_at = now() - timedelta(days=1)

    def fail(*args):
        raise TimeoutError()

    monkeypatch.setattr(integration_worker, "analyze", fail)
    assert integration_worker.tick(app.state.factory, None)
    with app.state.factory() as session:
        incident = session.scalar(select(Incident))
        assert incident.severity == "critical"
        assert incident.analysis["provider"] == "deterministic"
        task = session.scalar(select(Task).where(Task.kind == "ai"))
        assert task.state == "queued" and task.attempts == 1


def test_notification_dedup_per_severity_and_mock_delivery(app, monkeypatch):
    for payload in scenario():
        process(app, payload)
    with app.state.factory.begin() as session:
        tasks = session.scalars(select(Task).where(Task.kind == "discord")).all()
        assert len(tasks) == 2  # One high notification, then one critical escalation.
        tasks[0].due_at = now() - timedelta(days=1)
    sent = []
    monkeypatch.setattr(integration_worker, "notify", lambda *args: sent.append(args))
    integration_worker.tick(app.state.factory, None)
    assert len(sent) == 1
    with app.state.factory() as session:
        assert session.scalar(select(Task).where(Task.kind == "discord", Task.state == "done"))


def test_concurrent_duplicate_processing_is_idempotent(app):
    payload = event(event_type="privileged_user_created")
    with app.state.factory.begin() as session:
        jobs = [Job(payload=payload), Job(payload=payload)]
        session.add_all(jobs)
        session.flush()
        ids = [j.id for j in jobs]
    rules = load_rules("rules/detections.yaml")
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(lambda job: execute(app.state.factory, job, rules), ids))
    with app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(Event)) == 1
        assert session.scalar(select(func.count()).select_from(Incident)) == 1


def test_search_time_request_id_and_safe_export(app, client, headers):
    process(app, event(event_type="heartbeat", request_id="trace-42", message='=HYPERLINK("bad")'))
    data = client.get("/api/v1/search?request_id=trace-42", headers=headers).json()
    assert data["total"] == 1
    assert client.get("/api/v1/search?start=2020-01-01T00:00:00", headers=headers).status_code == 422
    result = client.get("/api/v1/events/export", headers=headers)
    assert result.status_code == 200
    assert "'=HYPERLINK" in result.text


def test_integration_replay_is_audited(app, client, headers):
    with app.state.factory.begin() as session:
        session.add(Task(id="dead-task", kind="search", target="missing", state="dead", attempts=5))
    assert client.post("/api/v1/tasks/dead-task/replay", headers=headers).status_code == 200
    assert any(
        a["action"] == "integration_replayed"
        for a in client.get("/api/v1/audit", headers=headers).json()["items"]
    )


def test_ai_schema_validation_and_evidence_references(app, monkeypatch):
    import json
    import httpx
    import pytest
    from sentinel.integrations import analyze
    from sentinel import integrations

    for payload in scenario():
        process(app, payload)
    with app.state.factory() as session:
        incident_id = session.scalar(select(Incident.id))
    settings = app.state.settings
    settings.ai_enabled = True
    forged = False

    class ModelClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def post(self, url, **kwargs):
            context = json.loads(kwargs["json"]["messages"][1]["content"])
            event_id = context["events"][0]["event_id"]
            body = {
                "summary": "Suspicious authentication activity requires review.",
                "observations": [
                    {
                        "text": "Authentication telemetry observed.",
                        "event_ids": ["invented" if forged else event_id],
                    }
                ],
                "possible_cause": "Unconfirmed credential misuse",
                "potential_impact": "Unknown",
                "investigation_steps": ["Verify account ownership."],
                "recommended_actions": ["Preserve evidence."],
                "confidence": "low",
            }
            return httpx.Response(
                200, json={"message": {"content": json.dumps(body)}}, request=httpx.Request("POST", url)
            )

    monkeypatch.setattr(integrations.httpx, "Client", ModelClient)
    result = analyze(app.state.factory, settings, incident_id)
    assert result["provider"] == "ollama" and result["read_only"]
    forged = True
    with pytest.raises(ValueError, match="Unknown evidence"):
        analyze(app.state.factory, settings, incident_id)


def test_stale_ai_result_cannot_overwrite_newer_evidence(app, monkeypatch):
    for payload in scenario():
        process(app, payload)
    with app.state.factory.begin() as session:
        task = session.scalar(select(Task).where(Task.kind == "ai"))
        task.due_at = now() - timedelta(days=1)
        task_id = task.id

    def response(*args):
        with app.state.factory.begin() as session:
            session.get(Task, task_id).generation += 1
        return {"provider": "fake-stale"}

    monkeypatch.setattr(integration_worker, "analyze", response)
    integration_worker.tick(app.state.factory, None)
    with app.state.factory() as session:
        assert session.scalar(select(Incident)).analysis["provider"] == "deterministic"
        assert session.get(Task, task_id).state == "queued"


def test_retention_preserves_incident_evidence(app):
    from sentinel.integrations import retention

    for payload in scenario():
        process(app, payload)
    unrelated = event(event_type="heartbeat")
    unrelated["timestamp"] = (now() - timedelta(days=60)).isoformat() + "Z"
    process(app, unrelated)
    settings = app.state.settings
    assert retention(app.state.factory, settings) == 1
    with app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(Event)) == 33


def test_disabled_integrations_do_not_call_providers(app, monkeypatch):
    from sentinel.integrations import Disabled, analyze, notify, index_event
    import pytest

    settings = app.state.settings
    for call in [
        lambda: analyze(app.state.factory, settings, "missing"),
        lambda: notify(settings, "slack", "test", {}),
        lambda: index_event(settings, {}),
    ]:
        with pytest.raises(Disabled):
            call()


def test_original_database_upgrade_preserves_users(tmp_path):
    from alembic.config import Config
    from alembic import command
    from sqlalchemy import create_engine, text
    from sentinel.models import database, User

    url = "sqlite:///" + str(tmp_path / "legacy.db")
    engine = create_engine(url)
    config = Config("alembic.ini")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "0001")
        connection.execute(
            text("INSERT INTO users (username,password_hash,role) VALUES ('legacy','hash','viewer')")
        )
        connection.execute(text("DROP TABLE alembic_version"))
    factory = database(url)
    with factory() as session:
        assert session.get(User, "legacy").role == "viewer"
        assert session.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0003"
        assert session.execute(text("PRAGMA foreign_keys")).scalar() == 1
