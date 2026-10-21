import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from sqlalchemy import select

from .models import Alert, Event, Incident, Job, Asset, RuleState
from .outbox import schedule
from .schema import normalize

RANK = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
CLOSED = {"RESOLVED", "FALSE_POSITIVE"}


def load_rules(path):
    rules = yaml.safe_load(Path(path).read_text())
    assert len({r["id"] for r in rules}) == len(rules), "Rule IDs must be unique"
    for rule in rules:
        assert rule["severity"] in RANK
        assert 1 <= rule["count"] <= 10000
        assert 1 <= rule["within_seconds"] <= 3600
        for field, conditions in rule["match"].items():
            for op, expected in conditions.items():
                assert op in {"eq", "in", "contains", "gte", "regex"}
                if op == "regex":
                    re.compile(expected)
    return rules


def matches(data, conditions):
    for field, operations in conditions.items():
        value = data.get(field)
        for operation, expected in operations.items():
            if value is None:
                return False
            if operation == "eq" and value != expected:
                return False
            if operation == "in" and value not in expected:
                return False
            if operation == "contains" and expected not in str(value):
                return False
            if operation == "gte" and value < expected:
                return False
            if operation == "regex" and not re.search(expected, str(value)):
                return False
    return True


def assessment(alerts):
    names = list(dict.fromkeys(a.title for a in alerts))
    return {
        "provider": "deterministic",
        "label": "Evidence-based playbook · AI provider not connected",
        "summary": f"{len(alerts)} detection(s) observed: "
        + "; ".join(names)
        + ". This is suspicious activity, not confirmation of compromise.",
        "observations": names,
        "investigation_steps": [
            "Verify the source and account owner against expected activity.",
            "Review the event timeline and successful authentication records.",
            "Check application audit logs for changes made after authentication.",
        ],
        "recommended_actions": [
            "Preserve relevant evidence before changing the affected system.",
            "If unauthorized access is confirmed, follow your account containment runbook.",
        ],
        "confidence": "Not scored; deterministic rule matches only",
        "read_only": True,
    }


def process_job(session, job_id, rules):
    job = session.get(Job, job_id)
    if not job or job.state in {"done", "dead"}:
        return
    data = normalize(job.payload)
    if session.get(Event, data["event_id"]):
        job.state = "done"
        return
    timestamp = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00")).replace(tzinfo=None)
    # Separate environments, assets and services; missing IP never creates a global bucket.
    entity = json.dumps(
        [
            data["environment"],
            data["host"],
            data["service"],
            data["source_ip"] or data["username"] or "host-local",
        ]
    )
    current = Event(
        id=data["event_id"],
        timestamp=timestamp,
        entity=entity,
        source_ip=data["source_ip"],
        service=data["service"],
        event_type=data["event_type"],
        data=data,
    )
    session.add(current)
    session.flush()
    schedule(session, "search", current.id)
    overrides = {r.id: r.enabled for r in session.scalars(select(RuleState))}
    candidates = [rule for rule in rules if overrides.get(rule["id"], True) and matches(data, rule["match"])]
    if not candidates:
        job.state, job.error = "done", None
        return
    asset = session.scalar(
        select(Asset).where(
            Asset.host == data["host"],
            Asset.service == data["service"],
            Asset.environment == data["environment"],
        )
    )
    history = session.scalars(
        select(Event)
        .where(
            Event.entity == entity,
            Event.timestamp >= timestamp - timedelta(hours=1),
            Event.timestamp <= timestamp,
        )
        .order_by(Event.timestamp, Event.id)
    ).all()
    for rule in candidates:
        window = [e for e in history if e.timestamp >= timestamp - timedelta(seconds=rule["within_seconds"])]
        evidence = [e for e in window if matches(e.data, rule["match"])]
        if len(evidence) < rule["count"]:
            continue
        if preceding := rule.get("preceded_by"):
            prior = [e for e in window if e.timestamp < timestamp and matches(e.data, preceding["match"])]
            if preceding.get("same_username"):
                if not data["username"]:
                    continue
                prior = [e for e in prior if e.data.get("username") == data["username"]]
            if len(prior) < preceding["count"]:
                continue
            evidence = prior + evidence
        incident = session.scalar(
            select(Incident)
            .where(
                Incident.entity == entity,
                Incident.status.not_in(CLOSED),
                Incident.last_seen >= timestamp - timedelta(minutes=15),
                Incident.first_seen <= timestamp + timedelta(minutes=15),
            )
            .order_by(Incident.last_seen.desc())
        )
        if not incident:
            incident = Incident(
                entity=entity,
                title=rule["name"],
                severity=rule["severity"],
                service=data["service"],
                source_ip=data["source_ip"],
                first_seen=min(e.timestamp for e in evidence),
                last_seen=timestamp,
            )
            session.add(incident)
            session.flush()
        alert = session.scalar(
            select(Alert).where(
                Alert.incident_id == incident.id,
                Alert.rule_id == rule["id"],
                Alert.last_seen >= timestamp - timedelta(seconds=rule["suppression_seconds"]),
            )
        )
        if alert:
            alert.event_ids = list(dict.fromkeys(alert.event_ids + [e.id for e in evidence]))
            alert.first_seen = min(alert.first_seen, min(e.timestamp for e in evidence))
            alert.last_seen = max(alert.last_seen, timestamp)
        else:
            alert = Alert(
                incident_id=incident.id,
                rule_id=rule["id"],
                title=rule["name"],
                severity=rule["severity"],
                entity=entity,
                first_seen=min(e.timestamp for e in evidence),
                last_seen=timestamp,
                event_ids=[e.id for e in evidence],
                mitre=rule.get("mitre"),
            )
            session.add(alert)
        incident.last_seen = max(incident.last_seen, timestamp)
        incident.first_seen = min(incident.first_seen, min(e.timestamp for e in evidence))
        if RANK[rule["severity"]] > RANK[incident.severity]:
            incident.severity = rule["severity"]
        session.flush()
        alerts = session.scalars(select(Alert).where(Alert.incident_id == incident.id)).all()
        if {a.rule_id for a in alerts} & {"AUTH-002", "WEB-010"}:
            incident.title = "Potential account compromise"
        elif len(alerts) > 1:
            incident.title = f"Correlated suspicious activity on {data['service']}"
        if asset and asset.criticality == "critical" and incident.severity == "high":
            incident.severity = "critical"
        incident.analysis = assessment(alerts)
        schedule(session, "ai", incident.id, debounce=5)
        if incident.severity in {"high", "critical"}:
            for channel in ("slack", "discord", "email"):
                schedule(
                    session,
                    channel,
                    f"{incident.id}:{incident.severity}",
                    {"incident_id": incident.id, "severity": incident.severity},
                )
    job.state = "done"
    job.error = None
