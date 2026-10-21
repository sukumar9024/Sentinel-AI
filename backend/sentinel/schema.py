import re
import json
from datetime import datetime, timedelta, timezone
from ipaddress import ip_address
from typing import Literal
from urllib.parse import unquote, urlsplit
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator, model_validator

SECRET_KEY = re.compile(r"password|passwd|token|secret|authorization|cookie|api.?key", re.I)
SECRET_TEXT = re.compile(
    r"""(?i)(password|passwd|token|secret|api[_-]?key|authorization|cookie)([\s"']*[:=][\s"']*)(?:Bearer\s+)?[^\s,;&"']+"""
)


def redact(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if SECRET_KEY.search(k) else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return SECRET_TEXT.sub(r"\1\2[REDACTED]", value)
    return value


class IncomingEvent(BaseModel):
    event_id: UUID = Field(default_factory=uuid4)
    timestamp: datetime
    environment: Literal["local", "dev", "staging", "production"]
    source_type: Literal["application", "nginx", "auth", "container", "host"]
    host: str = Field(min_length=1, max_length=100)
    service: str = Field(min_length=1, max_length=100)
    message: str = Field(max_length=8192)
    event_type: str = Field(default="unknown", max_length=100)
    severity: Literal["info", "low", "medium", "high", "critical"] = "info"
    source_ip: str | None = None
    username: str | None = Field(default=None, max_length=100)
    http_path: str | None = Field(default=None, max_length=2048)
    http_method: str | None = Field(default=None, max_length=20)
    status_code: int | None = Field(default=None, ge=100, le=599)
    user_agent: str | None = Field(default=None, max_length=500)
    request_id: str | None = Field(default=None, max_length=100)
    latency_ms: float | None = Field(default=None, ge=0, le=3600000)
    attributes: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def event_size(self):
        if len(json.dumps(self.model_dump(mode="json")).encode()) > 16384:
            raise ValueError("Maximum event size is 16 KiB")
        return self

    @field_validator("timestamp")
    @classmethod
    def utc(cls, value):
        if value.tzinfo is None:
            raise ValueError("timestamp must include a timezone")
        if value > datetime.now(timezone.utc).replace(microsecond=0) + timedelta(minutes=5):
            raise ValueError("timestamp is too far in the future")
        return value.astimezone(timezone.utc)

    @field_validator("source_ip")
    @classmethod
    def ip(cls, value):
        return str(ip_address(value)) if value else None


class Batch(BaseModel):
    events: list[IncomingEvent] = Field(min_length=1, max_length=200)


def normalize(payload):
    data = redact(IncomingEvent.model_validate(payload).model_dump(mode="json"))
    data["raw_event"] = dict(data)
    message = data["message"]
    if data["source_type"] == "nginx" and data["event_type"] == "unknown":
        match = re.search(r'^(\S+) .*?"([A-Z]+) ([^ ]+) HTTP/[^"]+" (\d{3})', message)
        if not match:
            raise ValueError("Unsupported nginx access log format")
        data.update(
            source_ip=str(ip_address(match[1])),
            http_method=match[2],
            http_path=match[3],
            status_code=int(match[4]),
            event_type="http_request",
        )
    if data["source_type"] == "auth" and data["event_type"] == "unknown":
        match = re.search(
            r"(Failed|Accepted) (?:password|publickey) for (?:invalid user )?(\S+) from ([\da-fA-F.:]+)",
            message,
        )
        if not match:
            raise ValueError("Unsupported SSH authentication format")
        data.update(
            event_type="authentication_failure" if match[1] == "Failed" else "authentication_success",
            username=match[2],
            source_ip=str(ip_address(match[3])),
        )
    if data["http_path"]:
        data["http_path"] = redact(unquote(data["http_path"]))
        data["path_only"] = urlsplit(data["http_path"]).path
    return data
