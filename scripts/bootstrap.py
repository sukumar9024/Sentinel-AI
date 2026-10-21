"""Generate local secrets once; never replace an existing environment."""

import os
import secrets
from pathlib import Path

path = Path(".env")
if path.exists():
    print(".env already exists; preserved.")
else:
    values = {
        "JWT_SECRET": secrets.token_urlsafe(48),
        "COLLECTOR_KEY": secrets.token_urlsafe(32),
        "ADMIN_PASSWORD": secrets.token_urlsafe(18),
        "POSTGRES_PASSWORD": secrets.token_urlsafe(24),
        "DEMO_ENABLED": "true",
    }
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w") as file:
        file.write("\n".join(f"{key}={value}" for key, value in values.items()) + "\n")
    print("Created .env (owner read/write only). Username: admin. Read ADMIN_PASSWORD from .env to sign in.")
