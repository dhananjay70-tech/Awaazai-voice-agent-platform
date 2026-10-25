"""Alembic environment: uses the app's settings and models, so there is one source of truth.

Everything AwaazAI owns lives in the "awaazai" schema, including Alembic's own version
table, so migration tracking is isolated from other projects sharing the database.
"""

from alembic import context
from sqlalchemy import create_engine, pool

import app.models  # noqa: F401  (registers all tables on Base.metadata)
from app.core.config import get_settings
from app.db.base import SCHEMA, Base

config = context.config
target_metadata = Base.metadata


def _database_url():
    url = get_settings().sqlalchemy_database_url
    if url is None:
        raise SystemExit(
            "No database configured. Set DATABASE_URL (or POSTGRES_HOST/USER/PASSWORD/DB) in Backend/.env first."
        )
    return url


def include_object(obj, name, type_, reflected, compare_to):
    """Autogenerate must only look at the awaazai schema, never at other projects' tables."""
    if type_ == "table":
        return obj.schema == SCHEMA
    return True


def _configure(**kwargs) -> None:
    context.configure(
        target_metadata=target_metadata,
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_object=include_object,
        **kwargs,
    )


def _run() -> None:
    with context.begin_transaction():
        # The version table lives in the schema, so the schema must exist before Alembic creates it.
        context.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
        context.run_migrations()


def run_migrations_offline() -> None:
    """Emit SQL to stdout without connecting (alembic upgrade head --sql)."""
    _configure(
        url=_database_url().render_as_string(hide_password=False),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    _run()


def run_migrations_online() -> None:
    engine = create_engine(_database_url(), poolclass=pool.NullPool)
    with engine.connect() as connection:
        _configure(connection=connection)
        _run()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
