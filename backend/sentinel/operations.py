import csv
import hmac
import io
import json
from datetime import datetime, timezone
from typing import Literal
from uuid import NAMESPACE_URL, uuid5

import httpx
from fastapi import Body, Depends, Header, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import String, cast, func, or_, select

from .integrations import search_client
from .locking import pipeline_transaction
from .models import (
    Asset,
    AuthSession,
    Event,
    Heartbeat,
    Incident,
    RuleState,
    Task,
    User,
    UserAccess,
    now,
    serialize,
)
from .outbox import schedule
from .schema import IncomingEvent
from .security import password_hash
from .sessions import digest, issue, revoke_family


def utc(value):
    if value and value.tzinfo is None:
        raise HTTPException(422, "Time filters require a timezone")
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value else None


def install_routes(app, settings, factory, rules, auth, analyst, admin, audit, enqueue, limiter):
    class Refresh(BaseModel):
        refresh_token: str = Field(min_length=20, max_length=200)

    @app.post("/api/v1/auth/refresh")
    def refresh(body: Refresh):
        result = None
        with pipeline_transaction(factory) as session:
            row = session.scalar(
                select(AuthSession).where(AuthSession.refresh_hash == digest(body.refresh_token))
            )
            if row:
                access = session.get(UserAccess, row.username)
                if row.revoked or row.expires_at < now() or (access and not access.enabled):
                    revoke_family(session, row.family)
                else:
                    row.revoked = True
                    result = issue(session, settings, session.get(User, row.username), row.family)
                    audit(session, row.username, "session_refreshed", row.id)
        if not result:
            raise HTTPException(401, "Invalid or reused refresh token")
        return result

    @app.post("/api/v1/auth/logout")
    def logout(user=Depends(auth)):
        with factory.begin() as session:
            row = session.get(AuthSession, user["session_id"])
            revoke_family(session, row.family)
            audit(session, user["username"], "logout", row.id)
        return {"status": "signed_out"}

    @app.get("/api/v1/users")
    def users(user=Depends(admin)):
        with factory() as session:
            access = {row.username: row.enabled for row in session.scalars(select(UserAccess))}
            return {
                "items": [
                    {"username": row.username, "role": row.role, "enabled": access.get(row.username, True)}
                    for row in session.scalars(select(User).order_by(User.username))
                ]
            }

    class UserChange(BaseModel):
        role: Literal["administrator", "analyst", "viewer"] | None = None
        enabled: bool | None = None
        password: str | None = Field(default=None, min_length=12, max_length=1024)

    @app.patch("/api/v1/users/{username}")
    def change_user(username: str, body: UserChange, user=Depends(admin)):
        if username == user["username"] and (
            body.enabled is False or body.role not in {None, "administrator"}
        ):
            raise HTTPException(422, "Cannot disable or demote your own administrator account")
        with factory.begin() as session:
            row = session.get(User, username)
            if not row:
                raise HTTPException(404, "User not found")
            if body.role:
                row.role = body.role
            if body.password:
                row.password_hash = password_hash(body.password)
            if body.enabled is not None:
                access = session.get(UserAccess, username)
                if access:
                    access.enabled = body.enabled
                else:
                    session.add(UserAccess(username=username, enabled=body.enabled))
            for token in session.scalars(select(AuthSession).where(AuthSession.username == username)):
                token.revoked = True
            audit(
                session,
                user["username"],
                "user_updated",
                username,
                {"role": body.role, "enabled": body.enabled, "password_changed": bool(body.password)},
            )
        return {"status": "updated"}

    class RuleChange(BaseModel):
        enabled: bool

    @app.patch("/api/v1/rules/{rule_id}")
    def toggle(rule_id: str, body: RuleChange, user=Depends(admin)):
        if rule_id not in {r["id"] for r in rules}:
            raise HTTPException(404, "Rule not found")
        with factory.begin() as session:
            row = session.get(RuleState, rule_id)
            if row:
                row.enabled, row.updated_at = body.enabled, now()
            else:
                session.add(RuleState(id=rule_id, enabled=body.enabled))
            audit(session, user["username"], "rule_updated", rule_id, {"enabled": body.enabled})
        return {"id": rule_id, "enabled": body.enabled}

    class AssetBody(BaseModel):
        host: str = Field(min_length=1, max_length=100)
        service: str = Field(min_length=1, max_length=100)
        environment: Literal["local", "dev", "staging", "production"]
        owner: str = Field(min_length=1, max_length=100)
        criticality: Literal["low", "medium", "high", "critical"]

    @app.get("/api/v1/assets")
    def assets(limit: int = Query(100, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(auth)):
        with factory() as session:
            return {
                "items": [
                    serialize(a)
                    for a in session.scalars(select(Asset).order_by(Asset.host).limit(limit).offset(offset))
                ]
            }

    @app.post("/api/v1/assets", status_code=201)
    def asset(body: AssetBody, user=Depends(admin)):
        with pipeline_transaction(factory) as session:
            row = session.scalar(
                select(Asset).where(
                    Asset.host == body.host,
                    Asset.service == body.service,
                    Asset.environment == body.environment,
                )
            )
            if row:
                row.owner, row.criticality = body.owner, body.criticality
            else:
                row = Asset(**body.model_dump())
                session.add(row)
            session.flush()
            audit(session, user["username"], "asset_updated", row.id, body.model_dump())
            return serialize(row)

    @app.post("/api/v1/collectors/fluent-bit", status_code=202)
    def collect(
        records: list[dict] = Body(min_length=1, max_length=2000), x_api_key: str = Header(default="")
    ):
        if not hmac.compare_digest(x_api_key.encode(), settings.collector_key.encode()):
            raise HTTPException(401, "Invalid collector key")
        if not limiter.allow("collector", 120):
            raise HTTPException(429, "Collector rate limit exceeded")
        parsed = []
        try:
            for record in records:
                original = dict(record)
                if "log" in record:
                    try:
                        nested = json.loads(record["log"])
                        record = (
                            record | nested
                            if isinstance(nested, dict)
                            else record | {"message": record["log"]}
                        )
                    except (ValueError, TypeError):
                        record = record | {"message": record["log"]}
                timestamp = record.get("timestamp", record.get("time", record.get("date")))
                if isinstance(timestamp, (int, float)):
                    timestamp = datetime.fromtimestamp(timestamp, timezone.utc).isoformat()
                record["timestamp"] = timestamp
                record.setdefault("event_id", str(uuid5(NAMESPACE_URL, json.dumps(original, sort_keys=True))))
                parsed.append(IncomingEvent.model_validate(record))
        except (ValidationError, ValueError, TypeError) as error:
            raise HTTPException(
                422, "Collector record invalid; verify timestamp and source metadata"
            ) from error
        with factory.begin() as session:
            ids = enqueue(session, parsed)
        return {"accepted": len(ids)}

    @app.get("/api/v1/platform")
    def platform(user=Depends(auth)):
        with factory() as session:
            workers = [
                serialize(row)
                | {
                    "healthy": (now() - row.seen_at).total_seconds()
                    < (180 if row.name.startswith("integrations:") else 30)
                }
                for row in session.scalars(select(Heartbeat).order_by(Heartbeat.seen_at.desc()).limit(20))
            ]
            queues = session.execute(
                select(Task.kind, Task.state, func.count()).group_by(Task.kind, Task.state)
            ).all()
            return {
                "workers": workers,
                "integrations": [{"kind": k, "state": s, "count": c} for k, s, c in queues],
                "search_enabled": bool(settings.opensearch_url),
                "ai_enabled": settings.ai_enabled,
                "notifications_enabled": settings.notifications_enabled,
            }

    @app.get("/api/v1/tasks")
    def tasks(state: str | None = None, limit: int = Query(50, ge=1, le=100), user=Depends(admin)):
        with factory() as session:
            query = select(Task)
            if state:
                query = query.where(Task.state == state)
            return {
                "items": [
                    serialize(t) for t in session.scalars(query.order_by(Task.created_at.desc()).limit(limit))
                ]
            }

    @app.post("/api/v1/tasks/{task_id}/replay")
    def replay(task_id: str, user=Depends(admin)):
        with pipeline_transaction(factory) as session:
            row = session.get(Task, task_id)
            if not row or row.state not in {"dead", "disabled"}:
                raise HTTPException(404, "Replayable integration task not found")
            row.state, row.attempts, row.error, row.due_at = "queued", 0, None, now()
            audit(session, user["username"], "integration_replayed", task_id)
        return {"status": "queued"}

    @app.post("/api/v1/incidents/{incident_id}/analysis", status_code=202)
    def analysis(incident_id: str, user=Depends(analyst)):
        if not settings.ai_enabled:
            raise HTTPException(409, "AI disabled; configure a local Ollama model first")
        if not limiter.allow("ai-request", 10):
            raise HTTPException(429, "Analysis request limit exceeded")
        with pipeline_transaction(factory) as session:
            if not session.get(Incident, incident_id):
                raise HTTPException(404, "Incident not found")
            schedule(session, "ai", incident_id)
            audit(session, user["username"], "ai_requested", incident_id)
        return {"status": "queued"}

    @app.get("/api/v1/search")
    def search(
        q: str = "",
        source_ip: str | None = None,
        service: str | None = None,
        request_id: str | None = None,
        event_type: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0, le=9900),
        user=Depends(auth),
    ):
        start, end = utc(start), utc(end)
        if start and end and start > end:
            raise HTTPException(422, "Start must precede end")
        # Fall back to relational evidence if search is unavailable; explicitly label the backend.
        if settings.opensearch_url:
            filters = [
                {"term": {k: v}}
                for k, v in {
                    "source_ip": source_ip,
                    "service": service,
                    "request_id": request_id,
                    "event_type": event_type,
                }.items()
                if v
            ]
            if start or end:
                filters.append(
                    {
                        "range": {
                            "timestamp": {
                                k: v.isoformat() + "Z" for k, v in {"gte": start, "lte": end}.items() if v
                            }
                        }
                    }
                )
            must = (
                [
                    {
                        "simple_query_string": {
                            "query": q,
                            "lenient": True,
                            "fields": ["message", "http_path", "service", "event_type", "source_ip"],
                        }
                    }
                ]
                if q
                else []
            )
            try:
                with search_client(settings) as client:
                    response = client.post(
                        "/security-events-*/_search",
                        json={
                            "query": {"bool": {"filter": filters, "must": must}},
                            "size": limit,
                            "from": offset,
                            "sort": [{"timestamp": "desc"}],
                            "track_total_hits": True,
                        },
                    )
                    response.raise_for_status()
                    data = response.json()["hits"]
                    return {
                        "items": [r["_source"] for r in data["hits"]],
                        "total": data["total"]["value"],
                        "backend": "opensearch",
                    }
            except (httpx.HTTPError, KeyError, ValueError):
                pass
        with factory() as session:
            query = select(Event)
            if q:
                query = query.where(
                    or_(cast(Event.data, String).ilike(f"%{q}%"), Event.service.ilike(f"%{q}%"))
                )
            for column, value in [
                (Event.source_ip, source_ip),
                (Event.service, service),
                (Event.event_type, event_type),
            ]:
                if value:
                    query = query.where(column == value)
            if request_id:
                query = query.where(Event.data["request_id"].as_string() == request_id)
            if start:
                query = query.where(Event.timestamp >= start)
            if end:
                query = query.where(Event.timestamp <= end)
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            return {
                "items": [
                    e.data
                    for e in session.scalars(
                        query.order_by(Event.timestamp.desc()).limit(limit).offset(offset)
                    )
                ],
                "total": total,
                "backend": "database-fallback" if settings.opensearch_url else "database",
            }

    @app.get("/api/v1/events/export")
    def export(q: str = "", user=Depends(analyst)):
        # Bounded export; prefix spreadsheet formula characters in untrusted log cells.
        with factory() as session:
            query = select(Event)
            if q:
                query = query.where(cast(Event.data, String).ilike(f"%{q}%"))
            rows = session.scalars(query.order_by(Event.timestamp.desc()).limit(1000)).all()
        output = io.StringIO()
        writer = csv.writer(output)
        columns = ["event_id", "timestamp", "service", "event_type", "source_ip", "message"]
        writer.writerow(columns)
        for row in rows:
            values = [str(row.data.get(c) or "") for c in columns]
            writer.writerow(
                ["'" + v if v.startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else v for v in values]
            )
        return Response(
            output.getvalue(),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=sentinel-events.csv"},
        )
