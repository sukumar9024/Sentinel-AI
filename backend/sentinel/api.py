import hmac
from datetime import timedelta
from typing import Literal

import jwt
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from .config import Settings
from .engine import CLOSED, load_rules
from .lab import scenario
from .models import Alert, Audit, Event, Incident, Job, Note, User, database, now, serialize
from .schema import Batch, IncomingEvent, redact
from .security import RateLimiter, SharedRateLimiter, RateLimitUnavailable, password_hash, verify
from .sessions import issue
from .operations import install_routes
from .models import AuthSession, UserAccess, RuleState, Heartbeat, Task


def create_app(settings=None):
    settings = settings or Settings()
    factory = database(settings.database_url)
    rules = load_rules(settings.rules_path)
    with factory.begin() as session:
        if not session.get(User, settings.admin_username):
            session.add(
                User(
                    username=settings.admin_username,
                    password_hash=password_hash(settings.admin_password),
                    role="administrator",
                )
            )
    app = FastAPI(title="SentinelAI", version="0.2.0", description="Deterministic security observability lab")
    app.state.factory = factory
    app.state.settings = settings
    app.state.rules = rules
    limiter = SharedRateLimiter(settings.redis_url) if settings.redis_url else RateLimiter()
    bearer = HTTPBearer(auto_error=False)

    @app.middleware("http")
    async def bounds(request: Request, call_next):
        # Read incrementally so chunked uploads cannot bypass the size limit.
        if request.method in {"POST", "PUT", "PATCH"}:
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > 512 * 1024:
                    return JSONResponse({"detail": "Maximum request size is 512 KiB"}, status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(RateLimitUnavailable)
    async def rate_limit_unavailable(request, error):
        return JSONResponse({"detail": "Rate limiting dependency unavailable"}, status_code=503)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Pydantic's default error response can echo supplied credentials or raw event data.
        return JSONResponse(
            {"detail": [{"loc": e["loc"], "type": e["type"], "msg": e["msg"]} for e in error.errors()]},
            status_code=422,
        )

    def auth(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        try:
            if not credentials:
                raise ValueError()
            claims = jwt.decode(
                credentials.credentials,
                settings.jwt_secret,
                algorithms=["HS256"],
                audience="sentinel-api",
                issuer="sentinel",
                options={"require": ["exp", "sub", "iat", "sid"]},
            )
            with factory() as session:
                user = session.get(User, claims["sub"])
                access = session.get(UserAccess, claims["sub"])
                login_session = session.get(AuthSession, claims["sid"])
                if (
                    not user
                    or (access and not access.enabled)
                    or not login_session
                    or login_session.revoked
                    or login_session.expires_at < now()
                    or login_session.username != user.username
                ):
                    raise ValueError()
                if not limiter.allow("management:" + user.username, 600):
                    raise HTTPException(429, "Management API rate limit exceeded")
                return {"username": user.username, "role": user.role, "session_id": login_session.id}
        except (jwt.PyJWTError, ValueError, KeyError):
            raise HTTPException(
                401, "Authentication required", headers={"WWW-Authenticate": "Bearer"}
            ) from None

    def analyst(user=Depends(auth)):
        if user["role"] not in {"administrator", "analyst"}:
            raise HTTPException(403, "Analyst role required")
        return user

    def admin(user=Depends(auth)):
        if user["role"] != "administrator":
            raise HTTPException(403, "Administrator role required")
        return user

    def audit(session, actor, action, target, detail=None):
        session.add(Audit(actor=actor, action=action, target=target, detail=redact(detail or {})))

    def enqueue(session, events):
        ids = []
        for item in events:
            clean = redact(item.model_dump(mode="json"))
            job = Job(payload=clean)
            session.add(job)
            session.flush()
            ids.append(job.id)
        return ids

    @app.get("/healthz")
    def health():
        with factory() as session:
            session.execute(select(1))
        return {"status": "ok", "service": "sentinel-api"}

    class Login(BaseModel):
        username: str = Field(max_length=100)
        password: str = Field(max_length=1024)

    @app.post("/api/v1/auth/login")
    def login(body: Login, request: Request):
        if not limiter.allow(f"login:{request.client.host}", 10):
            raise HTTPException(429, "Too many login attempts")
        with factory.begin() as session:
            user = session.get(User, body.username)
            valid = verify(body.password, user.password_hash) if user else verify(body.password, dummy_hash)
            access = session.get(UserAccess, body.username)
            if not user or not valid or (access and not access.enabled):
                audit(session, body.username, "login_failed", "auth")
            else:
                audit(session, user.username, "login", "auth")
                return issue(session, settings, user)
        raise HTTPException(401, "Invalid credentials")

    dummy_hash = password_hash("timing-comparison-only")

    @app.get("/api/v1/auth/me")
    def me(user=Depends(auth)):
        return user

    @app.post("/api/v1/events", status_code=202)
    def ingest(body: Batch, x_api_key: str = Header(default="")):
        if not hmac.compare_digest(x_api_key.encode(), settings.collector_key.encode()):
            raise HTTPException(401, "Invalid collector key")
        if not limiter.allow("collector", 120):
            raise HTTPException(429, "Collector rate limit exceeded")
        with factory.begin() as session:
            ids = enqueue(session, body.events)
        return {"accepted": len(ids), "job_ids": ids}

    @app.post("/api/v1/lab/run", status_code=202)
    def lab(user=Depends(admin)):
        if not settings.demo_enabled:
            raise HTTPException(403, "Lab is disabled; set DEMO_ENABLED=true locally")
        if not limiter.allow("lab", 3):
            raise HTTPException(429, "Wait before running another simulation")
        with factory.begin() as session:
            ids = enqueue(session, [IncomingEvent.model_validate(e) for e in scenario()])
            audit(session, user["username"], "lab_simulation", "account-compromise", {"events": len(ids)})
        return {
            "accepted": len(ids),
            "message": "Synthetic evidence queued. No network attack was performed.",
        }

    @app.get("/api/v1/dashboard")
    def dashboard(user=Depends(auth)):
        with factory() as session:

            def count(model, *where):
                return session.scalar(select(func.count()).select_from(model).where(*where))

            severities = dict(
                session.execute(
                    select(Incident.severity, func.count())
                    .where(Incident.status.not_in(CLOSED))
                    .group_by(Incident.severity)
                ).all()
            )
            services = session.execute(
                select(Event.service, func.count())
                .group_by(Event.service)
                .order_by(func.count().desc())
                .limit(5)
            ).all()
            recent = session.scalars(
                select(Event).where(Event.received_at >= now() - timedelta(hours=1))
            ).all()
            buckets = [0] * 30
            for event in recent:
                index = 29 - int((now() - event.received_at).total_seconds() // 120)
                if 0 <= index < 30:
                    buckets[index] += 1
            return {
                "events": count(Event),
                "alerts": count(Alert),
                "open_incidents": count(Incident, Incident.status.not_in(CLOSED)),
                "critical": severities.get("critical", 0),
                "high": severities.get("high", 0),
                "queued": count(Job, Job.state.in_(["queued", "published"])),
                "dead_letters": count(Job, Job.state == "dead"),
                "events_per_second": round(
                    count(Event, Event.received_at >= now() - timedelta(minutes=1)) / 60, 2
                ),
                "services": [{"name": name, "count": count_} for name, count_ in services],
                "activity": buckets,
                "rules": len(rules),
                "demo_enabled": settings.demo_enabled,
                "ai_enabled": settings.ai_enabled,
                "queue_backend": "Redis Streams + database outbox"
                if settings.redis_url
                else "Durable database queue",
            }

    @app.get("/api/v1/incidents")
    def incidents(
        status: str | None = None,
        severity: str | None = None,
        q: str = "",
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        user=Depends(auth),
    ):
        with factory() as session:
            query = select(Incident)
            if status:
                query = query.where(Incident.status == status)
            if severity:
                query = query.where(Incident.severity == severity)
            if q:
                query = query.where(
                    or_(
                        Incident.title.ilike(f"%{q}%"),
                        Incident.source_ip.ilike(f"%{q}%"),
                        Incident.service.ilike(f"%{q}%"),
                    )
                )
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            items = [
                serialize(i)
                for i in session.scalars(
                    query.order_by(Incident.last_seen.desc()).offset(offset).limit(limit)
                )
            ]
            return {"items": items, "total": total}

    @app.get("/api/v1/incidents/{incident_id}")
    def detail(incident_id: str, user=Depends(auth)):
        with factory() as session:
            incident = session.get(Incident, incident_id)
            if not incident:
                raise HTTPException(404, "Incident not found")
            alerts = session.scalars(
                select(Alert).where(Alert.incident_id == incident_id).order_by(Alert.first_seen)
            ).all()
            event_ids = list({eid for a in alerts for eid in a.event_ids})
            events = session.scalars(
                select(Event).where(Event.id.in_(event_ids)).order_by(Event.timestamp).limit(200)
            ).all()
            notes = session.scalars(
                select(Note).where(Note.incident_id == incident_id).order_by(Note.created_at)
            ).all()
            return {
                **serialize(incident),
                "alerts": [serialize(a) for a in alerts],
                "events": [e.data for e in events],
                "evidence_count": len(event_ids),
                "notes": [serialize(n) for n in notes],
            }

    class Update(BaseModel):
        status: (
            Literal["NEW", "ACKNOWLEDGED", "INVESTIGATING", "MITIGATED", "RESOLVED", "FALSE_POSITIVE"] | None
        ) = None
        owner: str | None = Field(default=None, max_length=100)
        resolution: str | None = Field(default=None, max_length=4000)

    @app.patch("/api/v1/incidents/{incident_id}")
    def update(incident_id: str, body: Update, user=Depends(analyst)):
        with factory.begin() as session:
            incident = session.get(Incident, incident_id)
            if not incident:
                raise HTTPException(404, "Incident not found")
            changes = body.model_dump(exclude_unset=True)
            if "status" in changes and changes["status"] is None:
                raise HTTPException(422, "Status cannot be null")
            effective_status = changes.get("status", incident.status)
            effective_resolution = changes.get("resolution", incident.resolution)
            if effective_status in CLOSED and not (effective_resolution or "").strip():
                raise HTTPException(422, "A resolution is required for a closed incident")
            if body.owner and not session.get(User, body.owner):
                raise HTTPException(422, "Owner must be an existing user")
            for key, value in changes.items():
                setattr(incident, key, redact(value))
            audit(session, user["username"], "incident_updated", incident_id, changes)
            return serialize(incident)

    class NoteBody(BaseModel):
        body: str = Field(min_length=1, max_length=4000)

    @app.post("/api/v1/incidents/{incident_id}/notes", status_code=201)
    def note(incident_id: str, body: NoteBody, user=Depends(analyst)):
        with factory.begin() as session:
            if not session.get(Incident, incident_id):
                raise HTTPException(404, "Incident not found")
            entry = Note(incident_id=incident_id, author=user["username"], body=redact(body.body))
            session.add(entry)
            audit(session, user["username"], "note_added", incident_id)
            session.flush()
            return serialize(entry)

    @app.get("/api/v1/events")
    def events(
        q: str = "",
        source_ip: str | None = None,
        service: str | None = None,
        event_type: str | None = None,
        limit: int = Query(50, ge=1, le=100),
        offset: int = Query(0, ge=0),
        user=Depends(auth),
    ):
        with factory() as session:
            query = select(Event)
            for column, value in [
                (Event.source_ip, source_ip),
                (Event.service, service),
                (Event.event_type, event_type),
            ]:
                if value:
                    query = query.where(column == value)
            if q:
                query = query.where(
                    or_(
                        Event.service.ilike(f"%{q}%"),
                        Event.event_type.ilike(f"%{q}%"),
                        Event.source_ip.ilike(f"%{q}%"),
                    )
                )
            total = session.scalar(select(func.count()).select_from(query.subquery()))
            return {
                "items": [
                    e.data
                    for e in session.scalars(
                        query.order_by(Event.timestamp.desc()).offset(offset).limit(limit)
                    )
                ],
                "total": total,
            }

    @app.get("/api/v1/rules")
    def rule_list(user=Depends(auth)):
        with factory() as session:
            overrides = {r.id: r.enabled for r in session.scalars(select(RuleState))}
            return {"items": [r | {"enabled": overrides.get(r["id"], True)} for r in rules]}

    @app.get("/api/v1/audit")
    def audits(limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user=Depends(admin)):
        with factory() as session:
            return {
                "items": [
                    serialize(a)
                    for a in session.scalars(
                        select(Audit).order_by(Audit.created_at.desc()).offset(offset).limit(limit)
                    )
                ]
            }

    class NewUser(BaseModel):
        username: str = Field(pattern=r"^[a-zA-Z0-9_.@-]{1,100}$")
        password: str = Field(min_length=12, max_length=1024)
        role: Literal["administrator", "analyst", "viewer"]

    @app.post("/api/v1/users", status_code=201)
    def add_user(body: NewUser, user=Depends(admin)):
        with factory.begin() as session:
            if session.get(User, body.username):
                raise HTTPException(409, "User exists")
            session.add(
                User(username=body.username, password_hash=password_hash(body.password), role=body.role)
            )
            audit(session, user["username"], "user_created", body.username, {"role": body.role})
        return {"username": body.username, "role": body.role}

    @app.get("/api/v1/dlq")
    def dlq(limit: int = Query(50, ge=1, le=100), user=Depends(admin)):
        with factory() as session:
            return {
                "items": [
                    serialize(j) for j in session.scalars(select(Job).where(Job.state == "dead").limit(limit))
                ]
            }

    @app.post("/api/v1/dlq/{job_id}/replay")
    def replay(job_id: str, user=Depends(admin)):
        with factory.begin() as session:
            job = session.get(Job, job_id)
            if not job or job.state != "dead":
                raise HTTPException(404, "Dead letter not found")
            job.state, job.attempts, job.error = "queued", 0, None
            audit(session, user["username"], "dlq_replayed", job_id)
        return {"status": "queued"}

    @app.get("/metrics")
    def metrics(x_api_key: str = Header(default="")):
        if not hmac.compare_digest(x_api_key.encode(), settings.collector_key.encode()):
            raise HTTPException(401, "Metrics key required")
        with factory() as session:
            values = {
                "events_stored": session.scalar(select(func.count()).select_from(Event)),
                "alerts_stored": session.scalar(select(func.count()).select_from(Alert)),
                "incidents_open": session.scalar(
                    select(func.count()).select_from(Incident).where(Incident.status.not_in(CLOSED))
                ),
                "queue_depth": session.scalar(
                    select(func.count()).select_from(Job).where(Job.state.in_(["queued", "published"]))
                ),
                "dead_letters": session.scalar(
                    select(func.count()).select_from(Job).where(Job.state == "dead")
                ),
            }
            for prefix in ("pipeline", "integrations"):
                seen = session.scalar(
                    select(func.max(Heartbeat.seen_at)).where(Heartbeat.name.like(prefix + ":%"))
                )
                values[prefix + "_heartbeat_age_seconds"] = (now() - seen).total_seconds() if seen else -1
            values["integration_failures"] = session.scalar(
                select(func.count()).select_from(Task).where(Task.state == "dead")
            )
        text = "".join(
            f"# HELP sentinel_{k} Current {k.replace('_', ' ')}\n# TYPE sentinel_{k} gauge\nsentinel_{k} {v}\n"
            for k, v in values.items()
        )
        return Response(text, media_type="text/plain; version=0.0.4")

    install_routes(app, settings, factory, rules, auth, analyst, admin, audit, enqueue, limiter)
    return app
