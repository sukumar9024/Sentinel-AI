"""Upgrade both new databases and the original v0.1 local database without deleting evidence."""

from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

LEGACY = {"users", "jobs", "events", "incidents", "alerts", "notes", "audit_logs"}


def upgrade(engine):
    root = Path.cwd()
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "migrations"))
    with engine.begin() as connection:
        if engine.dialect.name == "postgresql":
            connection.exec_driver_sql("SELECT pg_advisory_xact_lock(73854201)")
        config.attributes["connection"] = connection
        tables = set(inspect(connection).get_table_names())
        if "alembic_version" not in tables and LEGACY.issubset(tables):
            command.stamp(config, "0001")
        command.upgrade(config, "head")
