"""Isolated log-generating demo service. Never use its lab credentials for real authentication."""

import json
import os
from pathlib import Path
from datetime import datetime, timezone
from uuid import uuid4
from fastapi import FastAPI
from pydantic import BaseModel, Field
from .lab import scenario

app = FastAPI(title="SentinelAI telemetry source (lab only)")
log_path = Path(os.environ.get("LAB_LOG_PATH", "/logs/application.jsonl"))


def emit(event):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a") as file:
        file.write(json.dumps(event) + "\n")


@app.get("/healthz")
def health():
    return {"status": "ok"}


class Login(BaseModel):
    username: str = Field(max_length=100)
    password: str = Field(max_length=200)


@app.post("/login")
def login(body: Login):
    success = body.username == "lab-user" and body.password == "lab-only-password"
    emit(
        {
            "event_id": str(uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "environment": "local",
            "source_type": "application",
            "host": "sample-app",
            "service": "sample-login",
            "event_type": "authentication_success" if success else "authentication_failure",
            "source_ip": "192.0.2.10",
            "username": body.username,
            "message": "Lab login accepted" if success else "Lab login rejected",
            "status_code": 200 if success else 401,
            "http_path": "/login",
        }
    )
    return {"success": success, "lab_only": True}


@app.post("/scenario")
def run_scenario():
    events = scenario()
    for event in events:
        event["host"], event["service"] = "collected-host", "collected-identity"
        emit(event)
    return {"written": len(events)}
