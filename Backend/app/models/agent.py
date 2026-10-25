import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, String, Text, UniqueConstraint, func, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import SCHEMA, Base
from app.models.user import User

# JSONB on PostgreSQL, plain JSON elsewhere (the test database).
JsonType = JSON().with_variant(JSONB(), "postgresql")


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("owner_id", "name", name="uq_agents_owner_id_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey(f"{SCHEMA}.users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    description: Mapped[str | None] = mapped_column(String(500))
    system_prompt: Mapped[str] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(35), default="en")  # BCP 47 tag, e.g. "hi-IN"
    voice_config: Mapped[dict[str, Any]] = mapped_column(JsonType, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    owner: Mapped[User] = relationship(back_populates="agents")
