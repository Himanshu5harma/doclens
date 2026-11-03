"""Migrations use owner credentials, never the application's restricted role."""

import os

from alembic import context
from sqlalchemy import create_engine, pool

from doclens.service.models import Base, SCHEMA


url = os.environ.get("DOCLENS_MIGRATION_DATABASE_URL")
if not url:
    raise ValueError("Set DOCLENS_MIGRATION_DATABASE_URL for reviewed service migrations.")
engine = create_engine(url, poolclass=pool.NullPool, hide_parameters=True)
with engine.connect() as connection:
    context.configure(
        connection=connection, target_metadata=Base.metadata,
        include_schemas=True, version_table_schema=SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
