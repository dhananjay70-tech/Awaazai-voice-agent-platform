"""Add rate_limits table (login/register throttling counters)

Additive only: creates one table and one index inside the awaazai schema.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-19
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "awaazai"


def upgrade() -> None:
    op.create_table(
        "rate_limits",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_rate_limits")),
        schema=SCHEMA,
    )
    op.create_index("ix_rate_limits_window_start", "rate_limits", ["window_start"], unique=False, schema=SCHEMA)


def downgrade() -> None:
    op.drop_index("ix_rate_limits_window_start", table_name="rate_limits", schema=SCHEMA)
    op.drop_table("rate_limits", schema=SCHEMA)
