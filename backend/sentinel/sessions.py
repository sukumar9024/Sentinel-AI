import hashlib
import secrets
from datetime import timedelta
import jwt
from sqlalchemy import select
from .models import AuthSession, now, uid


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def issue(session, settings, user, family=None):
    refresh = secrets.token_urlsafe(48)
    row = AuthSession(
        id=uid(),
        family=family or uid(),
        username=user.username,
        refresh_hash=digest(refresh),
        expires_at=now() + timedelta(days=settings.refresh_days),
    )
    session.add(row)
    token = jwt.encode(
        {
            "sub": user.username,
            "sid": row.id,
            "iat": now(),
            "exp": now() + timedelta(minutes=settings.token_minutes),
            "aud": "sentinel-api",
            "iss": "sentinel",
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {
        "access_token": token,
        "refresh_token": refresh,
        "token_type": "bearer",
        "user": {"username": user.username, "role": user.role},
    }


def revoke_family(session, family):
    for row in session.scalars(select(AuthSession).where(AuthSession.family == family)):
        row.revoked = True
