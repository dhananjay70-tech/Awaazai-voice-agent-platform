"""Rate limiting of register/login, window resets, and client-IP handling behind proxies."""

import logging
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.core.client_ip import rate_limit_identity, resolve_client_ip
from app.main import create_app
from app.models.rate_limit import RateLimit
from app.services.rate_limiter import RateLimiter
from tests.conftest import make_settings

REGISTER = "/api/v1/auth/register"
LOGIN = "/api/v1/auth/login"
PASSWORD = "correct-horse-battery"


class FakeClock:
    def __init__(self):
        self.now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


@pytest.fixture
def clock():
    return FakeClock()


def build(database, clock, **overrides) -> TestClient:
    settings = make_settings(**overrides)
    app = create_app(settings=settings, database=database)
    app.state.rate_limiter = RateLimiter(database, settings, clock=clock)  # same limiter, controllable time
    return TestClient(app)


def register_user(client, email, headers=None):
    return client.post(REGISTER, json={"email": email, "password": PASSWORD}, headers=headers)


def login(client, email, password=PASSWORD, headers=None):
    return client.post(LOGIN, json={"email": email, "password": password}, headers=headers)


# ---------------------------------------------------------------- client IP resolution (pure function)

class TestResolveClientIp:
    def test_header_ignored_without_trusted_proxies(self):
        assert resolve_client_ip("10.0.0.1", "6.6.6.6", 0) == "10.0.0.1"

    def test_no_header_uses_peer(self):
        assert resolve_client_ip("10.0.0.1", None, 1) == "10.0.0.1"

    def test_one_trusted_proxy_uses_address_it_saw(self):
        assert resolve_client_ip("10.0.0.1", "203.0.113.7", 1) == "203.0.113.7"

    def test_client_cannot_spoof_by_prepending(self):
        # The client sent "6.6.6.6"; our proxy appended the real address after it.
        assert resolve_client_ip("10.0.0.1", "6.6.6.6, 203.0.113.7", 1) == "203.0.113.7"

    def test_two_trusted_proxies(self):
        assert resolve_client_ip("10.0.0.2", "6.6.6.6, 203.0.113.7, 10.0.0.1", 2) == "203.0.113.7"

    def test_shorter_chain_than_expected_falls_back_to_leftmost(self):
        assert resolve_client_ip("10.0.0.2", "203.0.113.7", 3) == "203.0.113.7"

    def test_garbage_entry_falls_back_to_peer(self):
        assert resolve_client_ip("10.0.0.1", "not-an-ip", 1) == "10.0.0.1"

    def test_ipv6_normalised(self):
        assert resolve_client_ip("10.0.0.1", "2001:DB8:0:0:0:0:0:1", 1) == "2001:db8::1"

    def test_ipv6_grouped_by_slash_64(self):
        assert rate_limit_identity("2001:db8:1:2::1") == rate_limit_identity("2001:db8:1:2:ffff::9")
        assert rate_limit_identity("2001:db8:1:2::1") != rate_limit_identity("2001:db8:1:3::1")
        assert rate_limit_identity("203.0.113.7") == "203.0.113.7"


# ---------------------------------------------------------------- register

def test_register_limit_then_429_with_standard_error(database, clock):
    with build(database, clock, rate_limit_register_max=3, rate_limit_register_window_seconds=600) as client:
        for i in range(3):
            assert register_user(client, f"user{i}@example.com").status_code == 201
        blocked = register_user(client, "user3@example.com")

    assert blocked.status_code == 429
    error = blocked.json()["error"]
    assert error["code"] == "rate_limited"
    assert error["request_id"] and error["message"]
    assert error["details"]["retry_after_seconds"] == 600
    assert blocked.headers["retry-after"] == "600"
    assert blocked.headers["x-content-type-options"] == "nosniff"  # still goes through security headers
    assert blocked.headers["cache-control"] == "no-store"


def test_blocked_register_creates_no_user(database, clock):
    with build(database, clock, rate_limit_register_max=1, rate_limit_register_window_seconds=60) as client:
        register_user(client, "first@example.com")
        assert register_user(client, "second@example.com").status_code == 429
        assert login(client, "first@example.com").status_code == 200
        clock.advance(61)
        # 201 (not 409) proves the blocked request never created the user
        assert register_user(client, "second@example.com").status_code == 201


def test_register_window_resets_and_retry_after_counts_down(database, clock):
    with build(database, clock, rate_limit_register_max=1, rate_limit_register_window_seconds=600) as client:
        assert register_user(client, "a@example.com").status_code == 201

        clock.advance(100)
        blocked = register_user(client, "b@example.com")
        assert blocked.status_code == 429
        assert blocked.headers["retry-after"] == "500"

        clock.advance(499)  # 1 second before the window ends
        still = register_user(client, "b@example.com")
        assert still.status_code == 429 and still.headers["retry-after"] == "1"

        clock.advance(1)  # window over
        assert register_user(client, "b@example.com").status_code == 201
        assert register_user(client, "c@example.com").status_code == 429  # and a fresh window starts counting


def test_invalid_register_requests_are_not_counted(database, clock):
    with build(database, clock, rate_limit_register_max=1) as client:
        assert client.post(REGISTER, json={"email": "bad"}).status_code == 422
        assert register_user(client, "ok@example.com").status_code == 201


# ---------------------------------------------------------------- login

def test_login_per_ip_limit(database, clock):
    with build(database, clock, rate_limit_login_ip_max=3, rate_limit_login_email_max=100) as client:
        register_user(client, "a@example.com")
        for i in range(3):
            assert login(client, f"nobody{i}@example.com", "wrong-password").status_code == 401
        blocked = login(client, "a@example.com")  # even the right password is refused while limited
    assert blocked.status_code == 429
    assert blocked.json()["error"]["code"] == "rate_limited"
    assert int(blocked.headers["retry-after"]) == 300


def test_login_per_email_limit_across_different_ips(database, clock):
    """An attacker rotating IPs against one account is still stopped."""
    with build(database, clock, trusted_proxy_count=1, rate_limit_login_email_max=3) as client:
        register_user(client, "victim@example.com", {"X-Forwarded-For": "198.51.100.1"})
        for i in range(3):
            response = login(client, "victim@example.com", "wrong-password", {"X-Forwarded-For": f"203.0.113.{i}"})
            assert response.status_code == 401
        blocked = login(client, "victim@example.com", PASSWORD, {"X-Forwarded-For": "203.0.113.99"})
        other_account = login(client, "someone-else@example.com", "x", {"X-Forwarded-For": "203.0.113.99"})
    assert blocked.status_code == 429
    assert int(blocked.headers["retry-after"]) == 900
    assert other_account.status_code == 401  # other accounts unaffected


def test_login_email_limit_is_case_insensitive(database, clock):
    with build(database, clock, rate_limit_login_email_max=2) as client:
        login(client, "Victim@Example.com", "x")
        login(client, "victim@example.COM", "x")
        assert login(client, "VICTIM@example.com", "x").status_code == 429


def test_login_limit_resets_after_window(database, clock):
    with build(database, clock, rate_limit_login_ip_max=2, rate_limit_login_ip_window_seconds=60) as client:
        register_user(client, "a@example.com")
        login(client, "a@example.com", "bad-password")
        login(client, "a@example.com", "bad-password")
        assert login(client, "a@example.com").status_code == 429
        clock.advance(61)
        success = login(client, "a@example.com")
    assert success.status_code == 200 and success.json()["access_token"]


def test_normal_login_behaviour_is_unchanged_under_limit(database, clock):
    with build(database, clock) as client:
        register_user(client, "a@example.com")
        wrong = login(client, "a@example.com", "wrong-password")
        right = login(client, "a@example.com")
    assert wrong.status_code == 401 and wrong.json()["error"]["code"] == "invalid_credentials"
    assert right.status_code == 200 and right.json()["token_type"] == "bearer"


# ---------------------------------------------------------------- behind proxies

def test_forwarded_header_ignored_when_no_trusted_proxy(database, clock):
    """Spoofing X-Forwarded-For must not give an attacker a fresh budget per request."""
    with build(database, clock, trusted_proxy_count=0, rate_limit_register_max=2) as client:
        for i in range(2):
            assert register_user(client, f"u{i}@example.com", {"X-Forwarded-For": f"1.1.1.{i}"}).status_code == 201
        blocked = register_user(client, "u9@example.com", {"X-Forwarded-For": "9.9.9.9"})
    assert blocked.status_code == 429


def test_each_client_behind_trusted_proxy_has_own_budget(database, clock):
    with build(database, clock, trusted_proxy_count=1, rate_limit_register_max=1) as client:
        a = {"X-Forwarded-For": "203.0.113.1"}
        b = {"X-Forwarded-For": "203.0.113.2"}
        assert register_user(client, "a1@example.com", a).status_code == 201
        assert register_user(client, "a2@example.com", a).status_code == 429
        assert register_user(client, "b1@example.com", b).status_code == 201  # different client, own budget


def test_prepended_fake_address_cannot_evade_limit_behind_trusted_proxy(database, clock):
    with build(database, clock, trusted_proxy_count=1, rate_limit_register_max=1) as client:
        # The (single) trusted proxy appends the real address, so anything before it is attacker-controlled.
        assert register_user(client, "a@example.com", {"X-Forwarded-For": "5.5.5.1, 203.0.113.1"}).status_code == 201
        blocked = register_user(client, "b@example.com", {"X-Forwarded-For": "5.5.5.2, 203.0.113.1"})
    assert blocked.status_code == 429


def test_ipv6_clients_share_a_slash_64_budget(database, clock):
    with build(database, clock, trusted_proxy_count=1, rate_limit_register_max=1) as client:
        assert register_user(client, "a@example.com", {"X-Forwarded-For": "2001:db8:1:2::1"}).status_code == 201
        blocked = register_user(client, "b@example.com", {"X-Forwarded-For": "2001:db8:1:2:aaaa::5"})
    assert blocked.status_code == 429


# ---------------------------------------------------------------- storage, privacy, switches

def test_stored_keys_are_hashed_not_raw(database, clock):
    with build(database, clock) as client:
        register_user(client, "private.person@example.com")
        login(client, "private.person@example.com", "x")
        with database.open_session() as session:
            rows = session.scalars(select(RateLimit)).all()
    assert len(rows) == 3  # register:ip, login:ip, login:email
    for row in rows:
        assert len(row.key) == 64 and all(c in "0123456789abcdef" for c in row.key)
        assert "private" not in row.key and "testclient" not in row.key


def test_counters_persist_even_when_the_request_fails(database, clock):
    """The attempt must count even if the request itself errors (e.g. wrong password -> 401)."""
    with build(database, clock, rate_limit_login_email_max=2, rate_limit_login_ip_max=100) as client:
        for _ in range(2):
            assert login(client, "x@example.com", "wrong-password").status_code == 401
        assert login(client, "x@example.com", "wrong-password").status_code == 429


def test_rate_limiting_can_be_disabled(database, clock):
    with build(database, clock, rate_limit_enabled=False, rate_limit_register_max=1) as client:
        assert register_user(client, "a@example.com").status_code == 201
        assert register_user(client, "b@example.com").status_code == 201
        with database.open_session() as session:
            assert session.scalars(select(RateLimit)).all() == []


def test_limiter_logs_scope_but_never_ip_or_email(database, clock, caplog):
    caplog.set_level(logging.WARNING)
    with build(database, clock, rate_limit_login_email_max=1) as client:
        login(client, "secret.person@example.com", "x")
        login(client, "secret.person@example.com", "x")
    assert "Rate limit hit: scope=login:email" in caplog.text
    assert "secret.person" not in caplog.text and "testclient" not in caplog.text


def test_expired_counters_are_cleaned_up(database, clock, monkeypatch):
    monkeypatch.setattr("app.services.rate_limiter.CLEANUP_PROBABILITY", 1.0)  # clean on every hit
    with build(database, clock) as client:
        register_user(client, "old@example.com")
        clock.advance(2 * 24 * 3600)  # two days later
        register_user(client, "new@example.com")
        with database.open_session() as session:
            rows = session.scalars(select(RateLimit)).all()
    assert len(rows) == 1  # the old window's row is gone, only the fresh one remains


def test_unrelated_endpoints_are_not_limited(database, clock):
    with build(database, clock, rate_limit_register_max=1, rate_limit_login_ip_max=1) as client:
        register_user(client, "a@example.com")
        for _ in range(5):
            assert client.get("/health").status_code == 200
            assert client.get("/api/v1/users/me").status_code == 401  # auth error, not 429


class TestSettingsValidation:
    @pytest.mark.parametrize("field", ["rate_limit_register_max", "rate_limit_login_ip_max", "rate_limit_login_email_max"])
    def test_limits_must_be_positive(self, field):
        with pytest.raises(Exception):
            make_settings(**{field: 0})

    def test_window_capped_at_one_day(self):
        with pytest.raises(Exception):
            make_settings(rate_limit_register_window_seconds=86_401)

    def test_trusted_proxy_count_range(self):
        with pytest.raises(Exception):
            make_settings(trusted_proxy_count=-1)

    def test_defaults_are_safe(self):
        s = make_settings()
        assert s.rate_limit_enabled is True and s.trusted_proxy_count == 0
