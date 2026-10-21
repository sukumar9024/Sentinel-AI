"""Serialize pipeline writes for correct cross-replica correlation (not a throughput claim)."""

from contextlib import contextmanager


@contextmanager
def pipeline_transaction(factory):
    with factory() as session:
        if session.bind.dialect.name == "sqlite":
            session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        else:
            # A database-wide lock also preserves order through shared threshold state.
            session.connection().exec_driver_sql("SELECT pg_advisory_xact_lock(73854202)")
        try:
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
