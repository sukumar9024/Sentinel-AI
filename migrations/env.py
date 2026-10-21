import os
from alembic import context
from sqlalchemy import create_engine, pool
from sentinel.models import Base

config = context.config
target_metadata = Base.metadata


def run(connection):
    context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(url=os.environ["DATABASE_URL"], target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif config.attributes.get("connection") is not None:
    run(config.attributes["connection"])
else:
    engine = create_engine(os.environ.get("DATABASE_URL", "sqlite:///./sentinel.db"), poolclass=pool.NullPool)
    with engine.connect() as connection:
        run(connection)
