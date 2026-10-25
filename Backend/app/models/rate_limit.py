from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RateLimit(Base):
    """One fixed-window counter per (scope, client) pair. `key` is an HMAC hash, never a raw IP or email."""

    __tablename__ = "rate_limits"
    __table_args__ = (Index("ix_rate_limits_window_start", "window_start"),)  # speeds up expired-row cleanup

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    count: Mapped[int] = mapped_column(Integer)
