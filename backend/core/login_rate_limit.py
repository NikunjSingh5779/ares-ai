"""Login brute-force rate limiter.

Uses in-process sliding windows with SHA-256 privacy-preserving keys.
Tracks two tiers per request:

1. **Email + client IP** (narrow, default: 5 attempts / 5 min)
2. **Client IP alone** (wide, default: 20 attempts / 15 min)

The narrow tier prevents repeated attempts against a single account.
The wide tier prevents attackers from rotating through email addresses
from the same IP.

Does **not** use Redis — counters are in-process and reset on restart.
This is acceptable as a first-line defence that protects against
long-running brute-force attacks even across worker restarts
(startup resets the window, which is strictly safer than carrying over
a stale limit).

Usage::

    from backend.core.login_rate_limit import login_rate_limiter

    # Before password verification:
    blocked = login_rate_limiter.check_and_record(email, client_ip)
    if blocked:
        raise HTTPException(status_code=429, ...)
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import TYPE_CHECKING

from prometheus_client import Counter

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger("ares.auth.rate_limit")

LOGIN_BLOCKED_TOTAL = Counter(
    "ares_login_blocked_total",
    "Total login attempts blocked by rate limiter",
    ["reason"],  # "email_ip" | "ip_only"
)


class SlidingWindow:
    """Sliding-window attempt counter backed by a list of timestamps.

    Thread-safe under the GIL for the in-process use case.
    """

    __slots__ = ("max_attempts", "window_seconds", "_attempts")

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._attempts: list[float] = []

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        while self._attempts and self._attempts[0] <= cutoff:
            self._attempts.pop(0)

    def attempt(self, now: float | None = None) -> bool:
        """Record one attempt. Returns ``True`` if under the limit, ``False`` if rate-limited.

        The attempt is recorded **only** when the method returns ``True``.
        """
        now = now if now is not None else time.monotonic()
        self._prune(now)
        if len(self._attempts) >= self.max_attempts:
            return False
        self._attempts.append(now)
        return True

    def retry_after(self, now: float | None = None) -> float:
        """Seconds until the oldest recorded attempt expires, or ``0.0`` if under the limit."""
        now = now if now is not None else time.monotonic()
        self._prune(now)
        if not self._attempts or len(self._attempts) < self.max_attempts:
            return 0.0
        remaining = (self._attempts[0] + self.window_seconds) - now
        return max(0.0, remaining)


class LoginRateLimiter:
    """Two-tier login rate limiter.

    Accepts a settings object duck-typed to the following attributes:

    * ``login_rate_limit_attempts``
    * ``login_rate_limit_window_seconds``
    * ``login_rate_limit_ip_attempts``
    * ``login_rate_limit_ip_window_seconds``
    * ``trusted_proxies``
    """

    def __init__(self, settings: object) -> None:
        _require_setting(settings, "login_rate_limit_attempts")
        _require_setting(settings, "login_rate_limit_window_seconds")
        _require_setting(settings, "login_rate_limit_ip_attempts")
        _require_setting(settings, "login_rate_limit_ip_window_seconds")
        _require_setting(settings, "trusted_proxies")

        self._email_attempt_limit: int = settings.login_rate_limit_attempts  # type: ignore[attr-defined]
        self._email_window_sec: int = settings.login_rate_limit_window_seconds  # type: ignore[attr-defined]
        self._ip_attempt_limit: int = settings.login_rate_limit_ip_attempts  # type: ignore[attr-defined]
        self._ip_window_sec: int = settings.login_rate_limit_ip_window_seconds  # type: ignore[attr-defined]
        self._trusted_proxies: str = settings.trusted_proxies  # type: ignore[attr-defined]

        # Per-(email+ip) sliding windows
        self._email_buckets: dict[str, SlidingWindow] = {}
        # Per-IP sliding windows
        self._ip_buckets: dict[str, SlidingWindow] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_and_record(self, email: str, client_ip: str, now: float | None = None) -> str | None:
        """Check and record a login attempt against both tiers.

        Returns ``None`` when the attempt is allowed, or a short reason
        string (``"email_ip"`` | ``"ip_only"``) when the attempt is
        blocked by that tier.

        The reason string is safe for metrics labels — it contains no
        user-identifiable data.
        """
        actual_now = now if now is not None else time.monotonic()
        normalized = self._normalize_email(email)
        hashed = self._hash_key(normalized, client_ip)

        # —— Tier 1: (email + IP) narrow throttling ——
        email_bucket = self._email_buckets.setdefault(
            hashed,
            SlidingWindow(self._email_attempt_limit, self._email_window_sec),
        )
        if not email_bucket.attempt(actual_now):
            LOGIN_BLOCKED_TOTAL.labels(reason="email_ip").inc()
            logger.warning(
                "Login rate limited (email+ip)",
                extra={"reason": "email_ip", "hash_prefix": hashed[:8]},
            )
            return "email_ip"

        # —— Tier 2: IP-only wide throttling ——
        ip_bucket = self._ip_buckets.setdefault(
            client_ip,
            SlidingWindow(self._ip_attempt_limit, self._ip_window_sec),
        )
        if not ip_bucket.attempt(actual_now):
            LOGIN_BLOCKED_TOTAL.labels(reason="ip_only").inc()
            logger.warning(
                "Login rate limited (ip only)",
                extra={"reason": "ip_only", "hash_prefix": hashed[:8]},
            )
            return "ip_only"

        return None

    def retry_after(self, email: str, client_ip: str, now: float | None = None) -> float:
        """Return the *Retry-After* value in seconds for the narrow tier, or ``0.0``."""
        hashed = self._hash_key(self._normalize_email(email), client_ip)
        bucket = self._email_buckets.get(hashed)
        return bucket.retry_after(now) if bucket else 0.0

    @staticmethod
    def get_client_ip(request: Request, trusted_proxies: str = "") -> str:
        """Extract the originating client IP from a request.

        *X-Forwarded-For* headers are **only** trusted when one or more
        ``trusted_proxies`` are configured.  Otherwise the direct peer
        IP (``request.client.host``) is used, which is safe when the
        application is fronted by a known reverse proxy.

        When ``trusted_proxies`` is set, the header is parsed left-to-right
        and the first IP that is **not** in the trusted set is returned.
        """
        if trusted_proxies:
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                # TODO: consider also checking X-Real-IP as a fallback
                proxies = {p.strip() for p in trusted_proxies.split(",")}
                for ip in (ip.strip() for ip in forwarded.split(",")):
                    if ip not in proxies:
                        return ip
        return request.client.host if request.client else "unknown"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_email(email: str) -> str:
        return email.strip().lower()

    @staticmethod
    def _hash_key(email: str, client_ip: str) -> str:
        raw = f"{email}|{client_ip}"
        return hashlib.sha256(raw.encode()).hexdigest()


def _require_setting(settings: object, name: str) -> None:
    if not hasattr(settings, name):
        raise TypeError(f"LoginRateLimiter received a settings object without the required attribute '{name}'")


# ------------------------------------------------------------------
# Module-level singleton — instantiated from global settings
# ------------------------------------------------------------------

from configs.settings import settings as _global_settings  # noqa: E402

login_rate_limiter = LoginRateLimiter(_global_settings)
