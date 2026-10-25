"""Create users and agents tables

Revision ID: 0001
Revises:
Create Date: 2026-10-18
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SCHEMA = "awaazai"  # frozen here on purpose: a migration must not change if app code changes


def upgrade() -> None:
    # Idempotent and additive: never touches the "public" schema or any other project's objects.
    op.execute(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=120), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        schema=SCHEMA,
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True, schema=SCHEMA)  # unique + indexed lookups

    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("language", sa.String(length=35), nullable=False),
        sa.Column(
            "voice_config",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(
            ["owner_id"], [f"{SCHEMA}.users.id"], name=op.f("fk_agents_owner_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
        sa.UniqueConstraint("owner_id", "name", name="uq_agents_owner_id_name"),
        schema=SCHEMA,
    )
    op.create_index(op.f("ix_agents_owner_id"), "agents", ["owner_id"], unique=False, schema=SCHEMA)


def downgrade() -> None:
    # Drops only AwaazAI's own tables. The schema itself is left in place (safer on a shared database).
    op.drop_index(op.f("ix_agents_owner_id"), table_name="agents", schema=SCHEMA)
    op.drop_table("agents", schema=SCHEMA)
    op.drop_index(op.f("ix_users_email"), table_name="users", schema=SCHEMA)
    op.drop_table("users", schema=SCHEMA)
