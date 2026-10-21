from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from sentinel.engine import load_rules, process_job
from sentinel.lab import scenario
from sentinel.models import Alert, Event, Incident, Job
from sentinel.schema import normalize
from sentinel.worker import execute

RULES = load_rules("rules/detections.yaml")
BASE_TIME = datetime.now(timezone.utc) - timedelta(hours=1)


def event(index=0, **changes):
    base = dict(
        event_id=str(uuid4()),
        timestamp=(BASE_TIME + timedelta(seconds=index)).isoformat(),
        environment="local",
        source_type="application",
        host="host-1",
        service="auth",
        source_ip="192.0.2.10",
        message="Test event",
    )
    return base | changes


def process(app, payload, rules=RULES):
    with app.state.factory.begin() as session:
        job = Job(payload=payload)
        session.add(job)
        session.flush()
        process_job(session, job.id, rules)
        return job.id


CASES = {
    "AUTH-001": {"event_type": "authentication_failure"},
    "AUTH-002": {"event_type": "authentication_success", "username": "alice"},
    "WEB-001": {"status_code": 401},
    "WEB-002": {"status_code": 403},
    "WEB-003": {"status_code": 404},
    "WEB-004": {"http_path": "/search?q=union%20select"},
    "WEB-005": {"http_path": "/files/../../etc/passwd"},
    "WEB-006": {"user_agent": "sqlmap/1.0"},
    "WEB-007": {"event_type": "http_request"},
    "WEB-008": {"status_code": 503},
    "WEB-009": {"http_path": "/admin/users", "status_code": 403},
    "WEB-010": {"http_path": "/admin/settings", "status_code": 200},
    "HOST-001": {"event_type": "authentication_failure"},
    "IAM-001": {"event_type": "privileged_user_created"},
    "IAM-002": {"event_type": "role_escalation"},
    "CONTAINER-001": {"event_type": "container_restart"},
    "CONTAINER-002": {"event_type": "privileged_container_started"},
    "APP-001": {"event_type": "application_error"},
    "APP-002": {"latency_ms": 5100},
}


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r["id"])
def test_each_rule_positive(app, rule):
    if previous := rule.get("preceded_by"):
        for i in range(previous["count"]):
            process(app, event(i, event_type="authentication_failure", username="alice"), [rule])
    for i in range(rule["count"]):
        payload = event(20 + i / 10, **CASES[rule["id"]])
        if rule["id"] == "HOST-001":
            payload["source_type"] = "auth"
        process(app, payload, [rule])
    with app.state.factory() as session:
        alert = session.scalar(select(Alert))
        assert alert is not None
        assert alert.rule_id == rule["id"]


@pytest.mark.parametrize("rule", RULES, ids=lambda r: r["id"])
def test_each_rule_benign_negative(app, rule):
    for i in range(max(rule["count"], 10)):
        process(
            app,
            event(
                i / 10,
                event_type="heartbeat",
                http_path="/health",
                status_code=200,
                user_agent="Mozilla/5.0",
                latency_ms=10,
            ),
            [rule],
        )
    with app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(Alert)) == 0


def test_full_scenario_deduplication_correlation_and_replay(app):
    payloads = scenario()
    for payload in payloads:
        process(app, payload)
    # Duplicate deliveries must not change counts or create additional alerts.
    for payload in payloads:
        process(app, payload)
    with app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(Event)) == 33
        incidents = session.scalars(select(Incident)).all()
        assert len(incidents) == 1
        assert incidents[0].title == "Potential account compromise"
        assert incidents[0].severity == "critical"
        alerts = session.scalars(select(Alert)).all()
        assert len(alerts) == 6
        assert len({a.rule_id for a in alerts}) == 6
        assert incidents[0].analysis["provider"] == "deterministic"


def test_threshold_boundary_and_time_window(app):
    rule = RULES[0]
    for i in range(9):
        process(app, event(i, event_type="authentication_failure"), [rule])
    with app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(Alert)) == 0
    process(app, event(100, event_type="authentication_failure"), [rule])
    with app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(Alert)) == 0


def test_entities_do_not_mix_environments_or_hosts(app):
    for i in range(12):
        payload = event(i, event_type="authentication_failure")
        payload["environment"] = "local" if i % 2 else "production"
        process(app, payload, [RULES[0]])
    with app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(Alert)) == 0


def test_success_requires_same_account(app):
    for i in range(6):
        process(app, event(i, event_type="authentication_failure", username="alice"), [RULES[1]])
    process(app, event(10, event_type="authentication_success", username="bob"), [RULES[1]])
    with app.state.factory() as session:
        assert session.scalar(select(func.count()).select_from(Alert)) == 0


def test_poison_event_retries_and_moves_to_dlq(app):
    payload = event()
    payload["source_type"] = "nginx"
    with app.state.factory.begin() as session:
        job = Job(payload=payload)
        session.add(job)
        session.flush()
        job_id = job.id
    for _ in range(3):
        assert not execute(app.state.factory, job_id, RULES)
    with app.state.factory() as session:
        job = session.get(Job, job_id)
        assert job.state == "dead"
        assert job.attempts == 3
        assert job.error == "ValueError"
        assert session.scalar(select(func.count()).select_from(Event)) == 0


def test_nginx_and_ssh_normalization():
    nginx = event()
    nginx.update(
        source_type="nginx",
        message='192.0.2.1 - - [01/Oct/2026:10:00:00 +0000] "GET /../etc/passwd HTTP/1.1" 403 42 "-" "curl"',
    )
    parsed = normalize(nginx)
    assert parsed["status_code"] == 403
    assert parsed["source_ip"] == "192.0.2.1"
    assert parsed["raw_event"]["message"] == nginx["message"]
    ssh = event()
    ssh.update(
        source_type="auth",
        message="sshd[42]: Failed password for invalid user root from 192.0.2.2 port 2222 ssh2",
    )
    parsed = normalize(ssh)
    assert parsed["username"] == "root"
    assert parsed["event_type"] == "authentication_failure"
