import hashlib
from datetime import timedelta
from .models import Task, now


def schedule(session, kind, target, payload=None, debounce=0):
    task_id = hashlib.sha256(f"{kind}:{target}".encode()).hexdigest()
    task = session.get(Task, task_id)
    if task:
        # Search deliveries and notifications are immutable; AI is refreshed as evidence changes.
        if kind != "ai":
            return
        task.generation += 1
        task.payload = payload or {}
        task.due_at = now() + timedelta(seconds=debounce)
        task.attempts = 0
        if task.state != "running":
            task.state = "queued"
    else:
        session.add(
            Task(
                id=task_id,
                kind=kind,
                target=target,
                payload=payload or {},
                due_at=now() + timedelta(seconds=debounce),
            )
        )
