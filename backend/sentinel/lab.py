from datetime import datetime, timedelta, timezone
from uuid import uuid4


def scenario():
    start = datetime.now(timezone.utc) - timedelta(seconds=50)
    base = dict(
        environment="local",
        source_type="application",
        host="identity-01",
        service="identity-api",
        source_ip="203.0.113.42",
        username="demo.analyst",
        message="Synthetic lab event",
    )
    events = []
    for i in range(25):
        events.append(
            dict(
                base,
                event_type="authentication_failure",
                status_code=401,
                http_path="/api/login",
                message="Lab: authentication failed",
            )
        )
    events.append(
        dict(
            base,
            event_type="authentication_success",
            status_code=200,
            http_path="/api/login",
            message="Lab: authentication succeeded",
        )
    )
    events.append(
        dict(
            base,
            event_type="http_request",
            status_code=200,
            http_path="/admin/settings",
            message="Lab: admin settings accessed",
        )
    )
    for i in range(6):
        events.append(
            dict(
                base,
                event_type="http_request",
                status_code=403,
                http_path="/admin/users",
                message="Lab: privileged operation denied",
            )
        )
    for i, item in enumerate(events):
        item.update(event_id=str(uuid4()), timestamp=(start + timedelta(seconds=i)).isoformat())
    return events
