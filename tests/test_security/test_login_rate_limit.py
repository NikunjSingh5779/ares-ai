"""Tests for login brute-force rate limiter.

Covers the :mod:`backend.core.login_rate_limit` module and its
integration into :mod:`backend.routers.auth`.

All tests use injected time (``now``) — no ``sleep`` calls.
"""

from __future__ import annotations

import re
from unittest.mock import MagicMock, PropertyMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.core.login_rate_limit import (
    LOGIN_BLOCKED_TOTAL,
    LoginRateLimiter,
    SlidingWindow,
)

# ======================================================================
# SlidingWindow unit tests
# ======================================================================


class TestSlidingWindow:
    """Standalone sliding-window behaviour."""

    def test_allows_up_to_limit(self) -> None:
        w = SlidingWindow(max_attempts=3, window_seconds=60)
        assert w.attempt(100.0) is True
        assert w.attempt(101.0) is True
        assert w.attempt(102.0) is True

    def test_blocks_at_limit(self) -> None:
        w = SlidingWindow(max_attempts=2, window_seconds=60)
        assert w.attempt(100.0) is True
        assert w.attempt(101.0) is True
        assert w.attempt(102.0) is False  # blocked

    def test_window_resets_after_expiry(self) -> None:
        w = SlidingWindow(max_attempts=2, window_seconds=60)
        assert w.attempt(100.0) is True
        assert w.attempt(101.0) is True
        assert w.attempt(102.0) is False  # blocked
        # After 61 seconds, the window should have room again
        assert w.attempt(162.0) is True  # first attempt expired

    def test_retry_after_zero_when_under_limit(self) -> None:
        w = SlidingWindow(max_attempts=5, window_seconds=60)
        assert w.retry_after(100.0) == 0.0

    def test_retry_after_positive_when_blocked(self) -> None:
        w = SlidingWindow(max_attempts=2, window_seconds=60)
        w.attempt(100.0)
        w.attempt(101.0)
        # Oldest attempt at 100.0 expires at 160.0 — 50 seconds from now
        ra = w.retry_after(110.0)
        assert 49.0 < ra <= 50.0

    def test_retry_after_decreases_over_time(self) -> None:
        w = SlidingWindow(max_attempts=2, window_seconds=60)
        w.attempt(100.0)
        w.attempt(101.0)
        ra1 = w.retry_after(110.0)
        ra2 = w.retry_after(130.0)
        assert ra2 < ra1  # decreasing

    def test_retry_after_zero_after_expiry(self) -> None:
        w = SlidingWindow(max_attempts=2, window_seconds=60)
        w.attempt(100.0)
        w.attempt(101.0)
        assert w.retry_after(200.0) == 0.0  # both expired


# ======================================================================
# LoginRateLimiter unit tests
# ======================================================================


class _FakeSettings:
    """Duck-typed settings object for tests."""

    login_rate_limit_attempts = 5
    login_rate_limit_window_seconds = 300
    login_rate_limit_ip_attempts = 20
    login_rate_limit_ip_window_seconds = 900
    trusted_proxies = ""


class TestLoginRateLimiterCheckAndRecord:
    """Two-tier rate limiter behaviour."""

    def make_limiter(
        self,
        email_limit: int = 5,
        email_window: int = 300,
        ip_limit: int = 20,
        ip_window: int = 900,
    ) -> LoginRateLimiter:
        settings = _FakeSettings()
        settings.login_rate_limit_attempts = email_limit
        settings.login_rate_limit_window_seconds = email_window
        settings.login_rate_limit_ip_attempts = ip_limit
        settings.login_rate_limit_ip_window_seconds = ip_window
        return LoginRateLimiter(settings)

    def test_allows_under_limit(self) -> None:
        limiter = self.make_limiter(email_limit=3)
        assert limiter.check_and_record("alice@example.com", "10.0.0.1", now=100.0) is None
        assert limiter.check_and_record("alice@example.com", "10.0.0.1", now=101.0) is None
        assert limiter.check_and_record("alice@example.com", "10.0.0.1", now=102.0) is None

    def test_blocks_at_email_limit(self) -> None:
        limiter = self.make_limiter(email_limit=2)
        assert limiter.check_and_record("alice@example.com", "10.0.0.1", now=100.0) is None
        assert limiter.check_and_record("alice@example.com", "10.0.0.1", now=101.0) is None
        blocked = limiter.check_and_record("alice@example.com", "10.0.0.1", now=102.0)
        assert blocked == "email_ip"

    def test_different_emails_same_ip_eventually_blocked_by_ip_tier(self) -> None:
        """Rotating emails from the same IP should hit the IP-only limit."""
        limiter = self.make_limiter(email_limit=5, ip_limit=3)
        assert limiter.check_and_record("alice@example.com", "10.0.0.1", now=100.0) is None
        assert limiter.check_and_record("bob@example.com", "10.0.0.1", now=101.0) is None
        assert limiter.check_and_record("carol@example.com", "10.0.0.1", now=102.0) is None
        # Fourth attempt from the same IP — should be blocked
        blocked = limiter.check_and_record("dave@example.com", "10.0.0.1", now=103.0)
        assert blocked == "ip_only"

    def test_different_ips_do_not_share_buckets(self) -> None:
        limiter = self.make_limiter(email_limit=2)
        limiter.check_and_record("alice@example.com", "10.0.0.1", now=100.0)
        limiter.check_and_record("alice@example.com", "10.0.0.1", now=101.0)
        # Same email, different IP — should be allowed
        assert limiter.check_and_record("alice@example.com", "10.0.0.2", now=102.0) is None
        assert limiter.check_and_record("alice@example.com", "10.0.0.2", now=103.0) is None
        # Fifth attempt from second IP should also block
        blocked = limiter.check_and_record("alice@example.com", "10.0.0.2", now=104.0)
        assert blocked == "email_ip"

    def test_window_reset_allows_new_attempts(self) -> None:
        limiter = self.make_limiter(email_limit=2, email_window=60)
        assert limiter.check_and_record("alice@example.com", "10.0.0.1", now=100.0) is None
        assert limiter.check_and_record("alice@example.com", "10.0.0.1", now=101.0) is None
        assert limiter.check_and_record("alice@example.com", "10.0.0.1", now=102.0) == "email_ip"
        # After the window expires
        assert limiter.check_and_record("alice@example.com", "10.0.0.1", now=200.0) is None

    def test_retry_after_returns_seconds(self) -> None:
        limiter = self.make_limiter(email_limit=2, email_window=60)
        assert limiter.retry_after("alice@example.com", "10.0.0.1", now=100.0) == 0.0
        limiter.check_and_record("alice@example.com", "10.0.0.1", now=100.0)
        limiter.check_and_record("alice@example.com", "10.0.0.1", now=101.0)
        # Oldest attempt at 100.0, expires at 160.0
        ra = limiter.retry_after("alice@example.com", "10.0.0.1", now=110.0)
        assert 49.0 < ra <= 50.0

    def test_normalize_email_case_and_whitespace(self) -> None:
        """Emails differing only by case/whitespace share the same bucket."""
        limiter = self.make_limiter(email_limit=1)
        assert limiter.check_and_record("Alice@Example.com", "10.0.0.1", now=100.0) is None
        blocked = limiter.check_and_record(" alice@example.com ", "10.0.0.1", now=101.0)
        assert blocked == "email_ip"

    def test_blanks_and_unknown_ip(self) -> None:
        """Blank email or missing client IP should not crash."""
        limiter = self.make_limiter(email_limit=5)
        assert limiter.check_and_record("", "unknown", now=100.0) is None
        assert limiter.check_and_record("", "unknown", now=101.0) is None

    def test_hash_key_is_deterministic(self) -> None:
        """Normalized emails produce the same hash key."""
        n1 = LoginRateLimiter._normalize_email("alice@example.com")
        n2 = LoginRateLimiter._normalize_email(" ALICE@Example.com ")
        h1 = LoginRateLimiter._hash_key(n1, "10.0.0.1")
        h2 = LoginRateLimiter._hash_key(n2, "10.0.0.1")
        assert h1 == h2

    def test_hash_key_contains_no_plaintext(self) -> None:
        h = LoginRateLimiter._hash_key("alice@example.com", "10.0.0.1")
        assert "alice" not in h
        assert "10.0.0.1" not in h

    def test_prometheus_labels_have_no_pii(self) -> None:
        """Metric label values must be fixed strings, not user data."""
        for sample in LOGIN_BLOCKED_TOTAL.collect():
            for s in sample.samples:
                for v in s.labels.values():
                    assert v in ("email_ip", "ip_only"), f"Unexpected label value: {v!r}"


# ======================================================================
# get_client_ip tests
# ======================================================================


def _make_request(client_host: str = "10.0.0.1", x_forwarded_for: str | None = None) -> MagicMock:
    """Build a minimal request mock."""
    req = MagicMock()
    type(req).client = PropertyMock(return_value=type("Client", (), {"host": client_host})())
    if x_forwarded_for is not None:
        req.headers = {"X-Forwarded-For": x_forwarded_for}
    else:
        req.headers = {}
    return req


class TestGetClientIP:
    def test_direct_connection(self) -> None:
        req = _make_request(client_host="10.0.0.1")
        ip = LoginRateLimiter.get_client_ip(req, trusted_proxies="")
        assert ip == "10.0.0.1"

    def test_proxy_trusted_header(self) -> None:
        """With trusted proxies, the untrusted IP is returned (right-to-left parsing).

        See TestGetClientIP's spoofing regression tests for cases where
        direction matters.
        """
        req = _make_request(client_host="192.168.1.1", x_forwarded_for="203.0.113.5, 192.168.1.1")
        ip = LoginRateLimiter.get_client_ip(req, trusted_proxies="192.168.1.1")
        assert ip == "203.0.113.5"

    def test_proxy_untrusted(self) -> None:
        """Without trusted_proxies, X-Forwarded-For is ignored."""
        req = _make_request(client_host="192.168.1.1", x_forwarded_for="203.0.113.5")
        ip = LoginRateLimiter.get_client_ip(req, trusted_proxies="")
        assert ip == "192.168.1.1"

    def test_proxy_chain_multiple_proxies(self) -> None:
        req = _make_request(
            client_host="10.0.0.5",
            x_forwarded_for="203.0.113.5, 10.0.0.1, 10.0.0.2",
        )
        ip = LoginRateLimiter.get_client_ip(req, trusted_proxies="10.0.0.1, 10.0.0.2")
        assert ip == "203.0.113.5"

    def test_no_client(self) -> None:
        req = MagicMock()
        req.client = None
        req.headers = {}
        ip = LoginRateLimiter.get_client_ip(req, trusted_proxies="")
        assert ip == "unknown"

    def test_proxy_all_trusted_falls_back_to_peer_ip(self) -> None:
        """If every forwarded IP is a trusted proxy, fall back to direct peer."""
        req = _make_request(client_host="10.0.0.1", x_forwarded_for="10.0.0.1")
        ip = LoginRateLimiter.get_client_ip(req, trusted_proxies="10.0.0.1")
        assert ip == "10.0.0.1"

    # --- Spoofing regression tests (Issue #1) -------------------------

    def test_right_to_left_rejects_spoofed_leftmost_ip(self) -> None:
        """Regression: attacker-supplied fake IP in leftmost position must
        NOT be returned as the client IP.

        With trusted_proxies="10.0.0.1" and a request whose
        X-Forwarded-For header was forged by the attacker as
        "203.0.113.99, 1.2.3.4" (where 1.2.3.4 is the real attacker IP
        appended by the first proxy) and whose direct peer is the trusted
        proxy at 10.0.0.1, the returned IP MUST be "1.2.3.4" — NOT the
        attacker-supplied "203.0.113.99".
        """
        req = _make_request(
            client_host="10.0.0.1",
            x_forwarded_for="203.0.113.99, 1.2.3.4",
        )
        ip = LoginRateLimiter.get_client_ip(req, trusted_proxies="10.0.0.1")
        assert ip == "1.2.3.4", (
            f"Expected '1.2.3.4' (real IP behind the proxy), got {ip!r} — "
            "attacker-supplied leftmost IP would have been returned"
        )

    def test_spoofing_ip_rotation_does_not_change_rate_limit_key(self) -> None:
        """An attacker who rotates a fake leftmost IP on every request
        must still be rate-limited to the real IP behind the trusted proxy.

        The attacker cycles through fake X-Forwarded-For values while using
        different email addresses, but the real IP (1.2.3.4) stays constant
        behind the proxy.  The IP-only tier should block after the 3rd
        attempt regardless of which email is tried.
        """
        # High email limit so the IP-only tier is what eventually blocks
        limiter = _rate_limiter_for_test(email_limit=100, ip_limit=3)
        limiter._trusted_proxies = "10.0.0.1"

        # Each fake IP is a different spoofed value the attacker cycles through
        fake_ips = ["203.0.113.1", "203.0.113.2", "203.0.113.3", "203.0.113.4", "203.0.113.5"]

        for i, fake_ip in enumerate(fake_ips):
            # Use a different email each time so we're testing IP-only blocking
            email = f"victim{i}@example.com"

            # Build a mock request simulating the proxy forwarding
            req = _make_request(
                client_host="10.0.0.1",
                x_forwarded_for=f"{fake_ip}, 1.2.3.4",
            )
            client_ip = LoginRateLimiter.get_client_ip(req, trusted_proxies="10.0.0.1")
            assert client_ip == "1.2.3.4", (
                f"Iteration {i}: expected client_ip '1.2.3.4', got {client_ip!r} "
                f"(fake IP {fake_ip} would have bypassed rate limiting)"
            )

            # All emails map to the same real IP bucket.
            # After the 3rd attempt the IP-tier should block.
            blocked = limiter.check_and_record(email, client_ip, now=100.0 + i * 10.0)
            if i < 3:
                assert blocked is None, f"Iteration {i}: should be allowed, got {blocked}"
            else:
                assert blocked == "ip_only", (
                    f"Iteration {i}: attacker should be blocked by IP limit, got {blocked!r}"
                )


# ======================================================================
# Integration: auth endpoint behaves correctly
# ======================================================================


@pytest.fixture
def app_with_mock_user(monkeypatch) -> FastAPI:
    """Build a minimal FastAPI app with the auth router, mocking the DB layer.

    Returns a (app, mock_user_service) tuple.
    """
    from backend.routers import auth as auth_router

    # Replace real DB dependencies with a mock user service
    mock_service = MagicMock()

    async def get_by_email(db, email: str):
        if email == "existing@example.com":
            user = MagicMock()
            user.email = "existing@example.com"
            user.password_hash = "mock_hash_that_wont_be_checked"
            user.is_active = True
            return user
        return None

    async def create_user(db, payload):
        user = MagicMock()
        user.email = payload.email
        user.display_name = payload.display_name
        user.role = payload.role
        user.id = "00000000-0000-0000-0000-000000000001"
        user.is_active = True
        return user

    mock_service.get_by_email = get_by_email
    mock_service.create_user = create_user

    monkeypatch.setattr(auth_router, "user_service", mock_service)
    # Mock verify_password so test doesn't depend on bcrypt/passlib compatibility
    monkeypatch.setattr(auth_router, "verify_password", lambda pw, _h: pw == "correct-password")

    app = FastAPI()
    app.include_router(auth_router.router)

    # Replace the global login_rate_limiter with a fresh one for each test
    monkeypatch.setattr(auth_router, "login_rate_limiter", _rate_limiter_for_test())

    return app


def _rate_limiter_for_test(
    email_limit: int = 5,
    email_window: int = 300,
    ip_limit: int = 20,
    ip_window: int = 900,
) -> LoginRateLimiter:
    s = _FakeSettings()
    s.login_rate_limit_attempts = email_limit
    s.login_rate_limit_window_seconds = email_window
    s.login_rate_limit_ip_attempts = ip_limit
    s.login_rate_limit_ip_window_seconds = ip_window
    return LoginRateLimiter(s)


class TestLoginEndpointRateLimit:
    """End-to-end tests for the /auth/login endpoint."""

    def test_successful_login(self, app_with_mock_user) -> None:
        app = app_with_mock_user
        with TestClient(app) as client:
            resp = client.post(
                "/auth/login",
                data={"username": "existing@example.com", "password": "correct-password"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            # Without a real password hash match, we expect 401 — not 429
            assert resp.status_code in (200, 401)
            assert "Retry-After" not in resp.headers

    def test_login_returns_429_after_exceeding_limit(self, monkeypatch, app_with_mock_user) -> None:
        """Exceed the narrow limit and verify 429."""
        app = app_with_mock_user
        # Inject a limiter with a tiny window so we don't need to send 5 requests
        tight_limiter = _rate_limiter_for_test(email_limit=2)
        from backend.routers import auth as auth_router

        monkeypatch.setattr(auth_router, "login_rate_limiter", tight_limiter)

        with TestClient(app) as client:
            # First attempt — should pass (or return 401 for wrong password)
            r1 = client.post(
                "/auth/login",
                data={"username": "existing@example.com", "password": "wrong-pass"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert r1.status_code in (200, 401)
            assert "Retry-After" not in r1.headers

            # Second attempt — still within limit
            r2 = client.post(
                "/auth/login",
                data={"username": "existing@example.com", "password": "wrong-pass"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert r2.status_code in (200, 401)
            assert "Retry-After" not in r2.headers

            # Third attempt — should be blocked with 429
            r3 = client.post(
                "/auth/login",
                data={"username": "existing@example.com", "password": "wrong-pass"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert r3.status_code == 429
            assert r3.json()["detail"] == "Too many login attempts. Please try again later."
            assert "Retry-After" in r3.headers
            retry_after = int(r3.headers["Retry-After"])
            assert 0 < retry_after <= 300  # within the window

    def test_429_before_db_lookup_no_enumeration(self, monkeypatch, app_with_mock_user) -> None:
        """When rate-limited, the endpoint must NOT query the DB at all.

        This prevents account enumeration via timing.
        """
        app = app_with_mock_user
        tight_limiter = _rate_limiter_for_test(email_limit=1)
        from backend.routers import auth as auth_router
        from backend.services import user_service

        monkeypatch.setattr(auth_router, "login_rate_limiter", tight_limiter)

        # Spy on get_by_email
        original_get_by_email = user_service.get_by_email

        call_count = 0

        async def spy_get_by_email(db, email):
            nonlocal call_count
            call_count += 1
            return await original_get_by_email(db, email)

        user_service.get_by_email = spy_get_by_email

        with TestClient(app) as client:
            # First attempt — consumes the bucket
            client.post(
                "/auth/login",
                data={"username": "existing@example.com", "password": "wrong"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            first_calls = call_count

            # Second attempt — should be blocked BEFORE db lookup
            r2 = client.post(
                "/auth/login",
                data={"username": "existing@example.com", "password": "wrong"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert r2.status_code == 429
            # Ensure no additional DB call was made
            assert call_count == first_calls, (
                f"get_by_email was called {call_count - first_calls} time(s) after rate limit"
            )

    def test_ip_only_blocks_email_rotation(self, monkeypatch, app_with_mock_user) -> None:
        """Different emails from the same IP eventually hit the IP limit."""
        app = app_with_mock_user
        tight_limiter = _rate_limiter_for_test(ip_limit=2, email_limit=5)
        from backend.routers import auth as auth_router

        monkeypatch.setattr(auth_router, "login_rate_limiter", tight_limiter)

        with TestClient(app) as client:
            # Use different emails from the same IP
            for i, email in enumerate(["a@test.com", "b@test.com"]):
                r = client.post(
                    "/auth/login",
                    data={"username": email, "password": "wrong"},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
                assert r.status_code in (200, 401), f"Attempt {i} should be allowed"

            # Third unique email from same IP should be blocked
            r3 = client.post(
                "/auth/login",
                data={"username": "c@test.com", "password": "wrong"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert r3.status_code == 429, "IP-only limit should block email rotation"

    def test_429_returns_retry_after(self, monkeypatch, app_with_mock_user) -> None:
        """Verify Retry-After header value."""
        app = app_with_mock_user
        tight_limiter = _rate_limiter_for_test(email_limit=1)
        from backend.routers import auth as auth_router

        monkeypatch.setattr(auth_router, "login_rate_limiter", tight_limiter)

        with TestClient(app) as client:
            # First attempt (consumes the bucket)
            client.post(
                "/auth/login",
                data={"username": "existing@example.com", "password": "wrong"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            # Blocked attempt
            r2 = client.post(
                "/auth/login",
                data={"username": "existing@example.com", "password": "wrong"},
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            assert r2.status_code == 429
            retry_after = r2.headers.get("Retry-After")
            assert retry_after is not None
            assert retry_after.isdigit()

    def test_different_ips_not_blocked(self, monkeypatch, app_with_mock_user) -> None:
        """Requests from different IPs should have independent rate limits.

        Uses a limiter with trusted_proxies so X-Forwarded-For is honoured.
        """
        app = app_with_mock_user
        tight_limiter = _rate_limiter_for_test(email_limit=1)
        from backend.routers import auth as auth_router
        from configs.settings import settings

        monkeypatch.setattr(auth_router, "login_rate_limiter", tight_limiter)
        monkeypatch.setattr(settings, "trusted_proxies", "10.0.0.1, 10.0.0.2")

        with TestClient(app) as client:
            # Exhaust the bucket from IP A
            client.post(
                "/auth/login",
                data={"username": "existing@example.com", "password": "wrong"},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Forwarded-For": "10.0.0.1",
                },
            )
            r_blocked = client.post(
                "/auth/login",
                data={"username": "existing@example.com", "password": "wrong"},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Forwarded-For": "10.0.0.1",
                },
            )
            assert r_blocked.status_code == 429, "Same IP should be blocked"

            # Different IP should still be allowed
            r_allowed = client.post(
                "/auth/login",
                data={"username": "existing@example.com", "password": "wrong"},
                headers={
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-Forwarded-For": "10.0.0.3",
                },
            )
            assert r_allowed.status_code in (200, 401), "Different IP should be allowed"


class TestRegisterEndpoint:
    """Verify /auth/register is NOT rate-limited by this feature."""

    def test_register_works(self, app_with_mock_user) -> None:
        app = app_with_mock_user
        with TestClient(app) as client:
            resp = client.post(
                "/auth/register",
                json={"email": "new@example.com", "display_name": "New User", "password": "pass1234"},
            )
            assert resp.status_code == 201


# ======================================================================
# Constructor validation
# ======================================================================


class TestConstructorValidation:
    def test_missing_settings_attr_raises(self) -> None:
        with pytest.raises(TypeError, match="login_rate_limit_attempts"):
            LoginRateLimiter(object())  # plain object has no required attrs

    def test_rejects_zero_attempts(self) -> None:
        """A limit of 0 would block everyone — the constructor does not enforce
        this (the runtime does), but the sliding window handles it."""
        limiter = _rate_limiter_for_test(email_limit=0)
        assert limiter.check_and_record("a@b.com", "1.2.3.4", now=100.0) is not None


# ======================================================================
# Bucket eviction tests (Issue #2)
# ======================================================================


class TestBucketEviction:
    """Bounded eviction for rate-limiter bucket dicts."""

    def make_limiter(self, max_email: int = 50_000, max_ip: int = 50_000) -> LoginRateLimiter:
        settings = _FakeSettings()
        settings.login_rate_limit_attempts = 3
        settings.login_rate_limit_window_seconds = 60
        settings.login_rate_limit_ip_attempts = 3
        settings.login_rate_limit_ip_window_seconds = 60
        return LoginRateLimiter(settings, max_email_buckets=max_email, max_ip_buckets=max_ip)

    def test_empty_bucket_removed_after_window_expires(self) -> None:
        """A bucket should be removed from the dict once its window fully expires.

        Uses ``retry_after`` (which prunes without recording a new attempt)
        for email buckets, and ``_sweep_empty_buckets`` for IP buckets.
        """
        limiter = self.make_limiter()
        email = "test@example.com"
        ip = "10.0.0.1"
        hashed = LoginRateLimiter._hash_key(LoginRateLimiter._normalize_email(email), ip)

        # Fill the bucket then let it expire
        assert limiter.check_and_record(email, ip, now=100.0) is None
        assert limiter.check_and_record(email, ip, now=101.0) is None
        assert limiter.check_and_record(email, ip, now=102.0) is None

        # Bucket still in dict (has active entries)
        assert hashed in limiter._email_buckets
        assert ip in limiter._ip_buckets

        # retry_after prunes the expired window and removes the empty email bucket
        assert limiter.retry_after(email, ip, now=200.0) == 0.0
        assert hashed not in limiter._email_buckets, (
            "Email bucket should be removed by retry_after after full expiry"
        )

        # _prune_and_sweep prunes expired entries then removes empty IP buckets
        limiter._prune_and_sweep(200.0)
        assert ip not in limiter._ip_buckets, (
            "IP bucket should be removed by sweep after full expiry"
        )

    def test_cap_limits_email_bucket_growth(self) -> None:
        """A burst of many unique keys should not grow past the cap."""
        max_buckets = 10
        limiter = self.make_limiter(max_email=max_buckets)

        # Create many unique email+ip combinations
        for i in range(100):
            email = f"user{i}@example.com"
            ip = f"10.0.0.{i % 255}"
            limiter.check_and_record(email, ip, now=100.0)

        # Should be bounded by the cap
        assert len(limiter._email_buckets) <= max_buckets, (
            f"Email buckets grew to {len(limiter._email_buckets)} (cap={max_buckets})"
        )

    def test_cap_limits_ip_bucket_growth(self) -> None:
        """A burst of many unique IPs should not grow past the cap."""
        max_buckets = 10
        limiter = self.make_limiter(max_ip=max_buckets)

        # Use the same email so we hit IP tier with many different IPs
        email = "victim@example.com"
        for i in range(100):
            ip = f"10.0.0.{i}"
            limiter.check_and_record(email, ip, now=100.0)

        # Should be bounded by the cap
        assert len(limiter._ip_buckets) <= max_buckets, (
            f"IP buckets grew to {len(limiter._ip_buckets)} (cap={max_buckets})"
        )

    def test_lru_evicts_least_recently_used_first(self) -> None:
        """The least recently used bucket should be evicted first when over cap."""
        max_buckets = 3
        limiter = self.make_limiter(max_email=max_buckets)

        # Create 3 buckets (fill the cap)
        limiter.check_and_record("a@example.com", "10.0.0.1", now=100.0)
        limiter.check_and_record("b@example.com", "10.0.0.2", now=100.0)
        limiter.check_and_record("c@example.com", "10.0.0.3", now=100.0)
        assert len(limiter._email_buckets) == 3

        # Re-access bucket 'a' to keep it warm, then add a new one
        limiter.check_and_record("a@example.com", "10.0.0.1", now=101.0)
        limiter.check_and_record("d@example.com", "10.0.0.4", now=102.0)

        # Should still be at cap (3). The evicted entry should be one of
        # the non-recently-used ones (b or c, not a or d).
        assert len(limiter._email_buckets) <= max_buckets
        # 'a' was recently accessed so should still be present
        hashed_a = LoginRateLimiter._hash_key(LoginRateLimiter._normalize_email("a@example.com"), "10.0.0.1")
        hashed_d = LoginRateLimiter._hash_key(LoginRateLimiter._normalize_email("d@example.com"), "10.0.0.4")
        assert hashed_a in limiter._email_buckets, "Recently-used bucket 'a' should survive eviction"
        assert hashed_d in limiter._email_buckets, "Newly-added bucket 'd' should be present"


# ======================================================================
# Logging safety
# ======================================================================


class TestLoggingSafety:
    """Verify the rate limiter does not emit PII in logs."""

    def test_log_lines_contain_no_plaintext_email(self, caplog, monkeypatch) -> None:
        import logging

        caplog.set_level(logging.WARNING)
        limiter = _rate_limiter_for_test(email_limit=0)  # blocks everything
        assert limiter.check_and_record("alice@example.com", "10.0.0.1", now=100.0) is not None

        for record in caplog.records:
            assert "alice@example.com" not in record.getMessage()
            assert "alice" not in record.getMessage()

    def test_extra_hash_prefix_not_full_hash(self, caplog, monkeypatch) -> None:
        import logging

        caplog.set_level(logging.WARNING)
        limiter = _rate_limiter_for_test(email_limit=0)
        limiter.check_and_record("alice@example.com", "10.0.0.1", now=100.0)

        for record in caplog.records:
            hp = getattr(record, "hash_prefix", None)
            if hp:
                assert len(hp) == 8, f"hash_prefix should be 8 chars, got {len(hp)}"
                assert re.match(r"^[a-f0-9]{8}$", hp), f"hash_prefix not hex: {hp}"
