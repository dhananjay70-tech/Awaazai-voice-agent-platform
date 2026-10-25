"""AwaazAI must live only in its own PostgreSQL schema, never in a shared "public" schema."""

import os
import re
import subprocess
import sys
from pathlib import Path

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

from app.db.base import SCHEMA, Base
import app.models  # noqa: F401

BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_schema_name():
    assert SCHEMA == "awaazai"


def test_every_table_is_in_awaazai_schema():
    assert {t.name for t in Base.metadata.tables.values()} == {"users", "agents", "rate_limits"}
    for table in Base.metadata.tables.values():
        assert table.schema == "awaazai", table.name


def test_foreign_keys_point_into_awaazai():
    for table in Base.metadata.tables.values():
        for fk in table.foreign_keys:
            assert fk.column.table.schema == "awaazai"


def test_orm_ddl_is_fully_schema_qualified():
    for table in Base.metadata.tables.values():
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert f"CREATE TABLE awaazai.{table.name}" in ddl
        assert "public." not in ddl
        for index in table.indexes:
            assert "awaazai." in str(CreateIndex(index).compile(dialect=postgresql.dialect()))


def test_migration_sql_only_touches_awaazai():
    """Render the real migration as PostgreSQL SQL (offline, no connection) and inspect every statement."""
    env = {**os.environ, "DATABASE_URL": "postgresql://u:p@localhost:5432/x"}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
        cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, result.stderr
    sql = result.stdout

    statements = [s.strip() for s in sql.split(";") if re.search(r"\b(CREATE|ALTER|DROP|INSERT|UPDATE|DELETE)\b", s)]
    assert statements
    assert statements[0].startswith("CREATE SCHEMA IF NOT EXISTS awaazai") or "CREATE SCHEMA IF NOT EXISTS awaazai" in statements[0]
    for statement in statements:
        if "CREATE SCHEMA IF NOT EXISTS awaazai" in statement:
            continue
        assert "awaazai." in statement, f"statement not scoped to awaazai: {statement[:120]}"
        assert "public." not in statement
    assert "CREATE TABLE awaazai.alembic_version" in sql  # version tracking is isolated too
    assert not re.search(r"\bDROP\b", sql)  # upgrade is purely additive
