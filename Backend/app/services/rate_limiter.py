"""Database-backed fixed-window rate limiter.

State lives in the awaazai.rate_limits table, so every worker and every server instance shares the same
counters (no Redis needed). Each attempt is one atomic "INSERT ... ON CONFLICT DO UPDATE", so concurrent
requests cannot undercount. Counters are committed in their own short transaction: an attempt counts even
if the request that made it later fails or rolls back.

Fixed windows are simple and cheap. Their known weakness is that a burst straddling a window boundary can
reach up to 2x the limit; that is acceptable for brute-force protection.

Assumes server clocks are roughly in sync (true on managed hosts running NTP).
"""

import hashlib
import hmac
import logging
import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import case, delete
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from app.core.client_ip import rate_limit_identity
from app.core.config import Settings
from app.core.errors import RateLimitedError
from app.db.session import Database
from app.models.rate_limit import RateLimit

logger = logging.getLogger(__name__)

CLEANUP_PROBABILITY = 0.01  # roughly 1 in 100 attempts also deletes long-expired counters
CLEANUP_AGE = timedelta(days=1)  # longer than any allowed window (max 86400 s)


@dataclass(frozen=True)
class Rule:
    scope: str
    max_attempts: int
    window_seconds: int


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RateLimiter:
    def __init__(
        self,
        database: Database,
        settings: Settings,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._database = database
        self._enabled = settings.rate_limit_enabled
        self._clock = clock
        # Keyed hash: stored keys can't be reversed into IPs/emails, and can't be precomputed without the secret.
        secret = settings.jwt_secret.get_secret_value() if settings.jwt_secret else "awaazai-rate-limit"
        self._hmac_key = secret.encode("utf-8")

        self.register_rule = Rule(
            "register:ip", settings.rate_limit_register_max, settings.rate_limit_register_window_seconds
        )
        self.login_ip_rule = Rule(
            "login:ip", settings.rate_limit_login_ip_max, settings.rate_limit_login_ip_window_seconds
        )
        self.login_email_rule = Rule(
            "login:email", settings.rate_limit_login_email_max, settings.rate_limit_login_email_window_seconds
        )

    # --- what the routes call ---

    def check_register(self, client_ip: str) -> None:
        self.hit(self.register_rule, rate_limit_identity(client_ip))

    def check_login(self, client_ip: str, email: str) -> None:
        self.hit(self.login_ip_rule, rate_limit_identity(client_ip))
        self.hit(self.login_email_rule, email.strip().lower())

    # --- internals ---

    def hit(self, rule: Rule, identifier: str) -> None:
        """Count one attempt; raise RateLimitedError if the caller is over the limit for this window."""
        if not self._enabled:
            return
        now = self._clock()
        key = self._key(rule.scope, identifier)

        with self._database.open_session() as session:
            count, window_start = self._increment(session, key, rule, now)
            if random.random() < CLEANUP_PROBABILITY:
                session.execute(delete(RateLimit).where(RateLimit.window_start < now - CLEANUP_AGE))
            session.commit()

        if count > rule.max_attempts:
            if window_start.tzinfo is None:  # SQLite (tests) returns naive UTC datetimes
                window_start = window_start.replace(tzinfo=timezone.utc)
            remaining = (window_start + timedelta(seconds=rule.window_seconds) - now).total_seconds()
            retry_after = max(1, math.ceil(remaining))
            logger.warning("Rate limit hit: scope=%s retry_after=%ds", rule.scope, retry_after)  # no IP/email logged
            raise RateLimitedError(retry_after)

    def _key(self, scope: str, identifier: str) -> str:
        return hmac.new(self._hmac_key, f"{scope}|{identifier}".encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def _increment(session: Session, key: str, rule: Rule, now: datetime) -> tuple[int, datetime]:
        """Atomically start a new window if the old one expired, otherwise add one. Returns (count, window_start)."""
        insert = postgresql_insert if session.get_bind().dialect.name == "postgresql" else sqlite_insert
        expired = RateLimit.window_start <= now - timedelta(seconds=rule.window_seconds)
        statement = (
            insert(RateLimit)
            .values(key=key, window_start=now, count=1)
            .on_conflict_do_update(
                index_elements=[RateLimit.key],
                set_={
                    "count": case((expired, 1), else_=RateLimit.count + 1),
                    "window_start": case((expired, now), else_=RateLimit.window_start),
                },
            )
            .returning(RateLimit.count, RateLimit.window_start)
        )
        count, window_start = session.execute(statement).one()
        return count, window_start
