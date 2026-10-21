from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Integer,
    String,
    Text,
    ForeignKey,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def uid():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(100), primary_key=True)
    password_hash: Mapped[str] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String(20))


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    payload: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Event(Base):
    __tablename__ = "events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    entity: Mapped[str] = mapped_column(String(500), index=True)
    source_ip: Mapped[str | None] = mapped_column(String(50), index=True)
    service: Mapped[str] = mapped_column(String(100), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    data: Mapped[dict] = mapped_column(JSON)


class Incident(Base):
    __tablename__ = "incidents"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    entity: Mapped[str] = mapped_column(String(500), index=True)
    title: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30), default="NEW", index=True)
    service: Mapped[str] = mapped_column(String(100))
    source_ip: Mapped[str | None] = mapped_column(String(50))
    owner: Mapped[str | None] = mapped_column(String(100))
    first_seen: Mapped[datetime] = mapped_column(DateTime)
    last_seen: Mapped[datetime] = mapped_column(DateTime, index=True)
    resolution: Mapped[str | None] = mapped_column(Text)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", name="fk_incident", ondelete="RESTRICT"), index=True
    )
    rule_id: Mapped[str] = mapped_column(String(50), index=True)
    title: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(20))
    entity: Mapped[str] = mapped_column(String(500), index=True)
    first_seen: Mapped[datetime] = mapped_column(DateTime)
    last_seen: Mapped[datetime] = mapped_column(DateTime)
    event_ids: Mapped[list] = mapped_column(JSON)
    mitre: Mapped[dict | None] = mapped_column(JSON)


class Note(Base):
    __tablename__ = "notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    incident_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("incidents.id", name="fk_incident", ondelete="RESTRICT"), index=True
    )
    author: Mapped[str] = mapped_column(
        String(100), ForeignKey("users.username", name="fk_note_author", ondelete="RESTRICT")
    )
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Audit(Base):
    __tablename__ = "audit_logs"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(100))
    detail: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)


def database(url):
    options = (
        {"connect_args": {"check_same_thread": False, "timeout": 30}} if url.startswith("sqlite") else {}
    )
    migrating = True
    engine = create_engine(url, **options)
    if url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def configure(conn, _):
            conn.execute("PRAGMA journal_mode=WAL")
            if not migrating:
                conn.execute("PRAGMA foreign_keys=ON")

    from .migrations import upgrade

    upgrade(engine)
    migrating = False
    engine.dispose()
    return sessionmaker(engine, expire_on_commit=False)


def serialize(row):
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


class Task(Base):
    """Durable integrations outbox. Stable IDs coalesce incident enrichment requests."""

    __tablename__ = "integration_tasks"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), index=True)
    target: Mapped[str] = mapped_column(String(100), index=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    generation: Mapped[int] = mapped_column(Integer, default=1)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    due_at: Mapped[datetime] = mapped_column(DateTime, default=now, index=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    error: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class Heartbeat(Base):
    __tablename__ = "worker_heartbeats"
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    detail: Mapped[dict] = mapped_column(JSON, default=dict)


class JobSchedule(Base):
    __tablename__ = "job_schedules"
    job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("jobs.id", name="fk_schedule_job", ondelete="CASCADE"), primary_key=True
    )
    due_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    published_at: Mapped[datetime | None] = mapped_column(DateTime)


class RuleState(Base):
    __tablename__ = "rule_states"
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)


class Asset(Base):
    __tablename__ = "assets"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    host: Mapped[str] = mapped_column(String(100))
    service: Mapped[str] = mapped_column(String(100))
    environment: Mapped[str] = mapped_column(String(20))
    owner: Mapped[str] = mapped_column(String(100))
    criticality: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (UniqueConstraint("host", "service", "environment"),)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=uid)
    family: Mapped[str] = mapped_column(String(36), index=True)
    username: Mapped[str] = mapped_column(String(100), index=True)
    refresh_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime)
    revoked: Mapped[bool] = mapped_column(default=False)


class UserAccess(Base):
    __tablename__ = "user_access"
    username: Mapped[str] = mapped_column(String(100), primary_key=True)
    enabled: Mapped[bool] = mapped_column(default=True)
