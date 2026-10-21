"""Local PostgreSQL backup and isolated restore drill; original database is never overwritten."""

import json
import subprocess
from pathlib import Path
from uuid import uuid4


def command(*args, **kwargs):
    return subprocess.run(
        ["docker", "compose", "exec", "-T", "postgres", *args], check=True, capture_output=True, **kwargs
    )


def main():
    directory = Path("backups")
    directory.mkdir(mode=0o700, exist_ok=True)
    archive = directory / ("sentinel-" + uuid4().hex + ".dump")
    archive.write_bytes(command("pg_dump", "-U", "sentinel", "-d", "sentinel", "-Fc").stdout)
    archive.chmod(0o600)
    database = "sentinel_restore_" + uuid4().hex[:12]
    command("createdb", "-U", "sentinel", database)
    try:
        command("pg_restore", "-U", "sentinel", "-d", database, "--no-owner", input=archive.read_bytes())
        counts = {}
        for table in ["events", "incidents", "alerts", "notes", "audit_logs"]:
            source = int(
                command(
                    "psql", "-U", "sentinel", "-d", "sentinel", "-Atc", f"SELECT count(*) FROM {table}"
                ).stdout
            )
            restored = int(
                command(
                    "psql", "-U", "sentinel", "-d", database, "-Atc", f"SELECT count(*) FROM {table}"
                ).stdout
            )
            # Run this drill with ingestion quiescent; live writes may legitimately change source counts.
            assert source == restored, f"Count mismatch for {table}; pause ingestion and repeat"
            counts[table] = restored
        print(json.dumps({"backup": str(archive), "restore_verified": counts}))
    finally:
        command("dropdb", "-U", "sentinel", database)


if __name__ == "__main__":
    main()
