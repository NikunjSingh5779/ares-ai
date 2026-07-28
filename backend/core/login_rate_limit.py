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
from collections import OrderedDict
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

    def __init__(self, settings: object, max_email_buckets: int = 50_000, max_ip_buckets: int = 50_000) -> None:
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

        # Per-(email+ip) sliding windows — OrderedDict for LRU eviction
        self._email_buckets: OrderedDict[str, SlidingWindow] = OrderedDict()
        self._max_email_buckets = max_email_buckets
        # Per-IP sliding windows — OrderedDict for LRU eviction
        self._ip_buckets: OrderedDict[str, SlidingWindow] = OrderedDict()
        self._max_ip_buckets = max_ip_buckets

        # Opportunistic pruning counter — sweeps empty buckets every N calls
        self._prune_counter = 0

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

        # Opportunistic sweep of empty buckets (roughly every 100 calls)
        self._prune_counter = (self._prune_counter + 1) % 100
        if self._prune_counter == 0:
            self._prune_and_sweep(actual_now)

        # —— Tier 1: (email + IP) narrow throttling ——
        email_bucket = self._get_or_create_bucket(
            self._email_buckets,
            hashed,
            self._email_attempt_limit,
            self._email_window_sec,
            self._max_email_buckets,
            actual_now,
        )
        if not email_bucket.attempt(actual_now):
            LOGIN_BLOCKED_TOTAL.labels(reason="email_ip").inc()
            logger.warning(
                "Login rate limited (email+ip)",
                extra={"reason": "email_ip", "hash_prefix": hashed[:8]},
            )
            return "email_ip"

        # —— Tier 2: IP-only wide throttling ——
        ip_bucket = self._get_or_create_bucket(
            self._ip_buckets,
            client_ip,
            self._ip_attempt_limit,
            self._ip_window_sec,
            self._max_ip_buckets,
            actual_now,
        )
        if not ip_bucket.attempt(actual_now):
            LOGIN_BLOCKED_TOTAL.labels(reason="ip_only").inc()
            logger.warning(
                "Login rate limited (ip only)",
                extra={"reason": "ip_only", "hash_prefix": hashed[:8]},
            )
            return "ip_only"

        return None

    def _get_or_create_bucket(
        self,
        buckets: OrderedDict[str, SlidingWindow],
        key: str,
        max_attempts: int,
        window_seconds: int,
        max_buckets: int,
        now: float | None = None,
    ) -> SlidingWindow:
        """Get an existing bucket or create a new one with LRU eviction."""
        if key in buckets:
            # Mark as recently used
            buckets.move_to_end(key)
            return buckets[key]

        # Enforce cap before creating
        self._evict_to_cap(buckets, max_buckets, now)

        bucket = SlidingWindow(max_attempts, window_seconds)
        buckets[key] = bucket
        return bucket

    @staticmethod
    def _evict_to_cap(
        buckets: OrderedDict[str, SlidingWindow],
        max_buckets: int,
        now: float | None = None,
    ) -> None:
        """Evict the oldest-inactive buckets until under the cap.

        If *now* is provided each bucket is pruned first so that expired
        entries are not counted toward its activity.  Then all empty
        buckets are removed, and if the dict is still over *max_buckets*
        the least-recently-used entries are evicted.
        """
        if len(buckets) < max_buckets:
            return

        # Phase 0: prune expired entries if we have a reference time
        if now is not None:
            for w in buckets.values():
                w._prune(now)

        # Phase 1: remove all empty buckets
        LoginRateLimiter._sweep_empty_buckets(buckets)

        # Phase 2: LRU-evict oldest if still over cap
        while buckets and len(buckets) >= max_buckets:
            buckets.popitem(last=False)  # remove the oldest (front)

    @staticmethod
    def _remove_if_empty(buckets: OrderedDict[str, SlidingWindow], key: str) -> None:
        """Remove the bucket at *key* if its window has no active attempts."""
        bucket = buckets.get(key)
        if bucket is not None and not bucket._attempts:
            del buckets[key]

    @staticmethod
    def _sweep_empty_buckets(buckets: OrderedDict[str, SlidingWindow]) -> None:
        """Remove all buckets whose window has no active attempts (caller should prune first)."""
        empty_keys = [k for k, w in buckets.items() if not w._attempts]
        for k in empty_keys:
            del buckets[k]

    def _prune_and_sweep(
        self,
        now: float,
    ) -> None:
        """Prune every bucket in both dicts, then remove empty ones.

        Called periodically from :meth:`check_and_record` to reclaim
        memory from buckets whose windows have fully expired.
        """
        for w in self._email_buckets.values():
            w._prune(now)
        self._sweep_empty_buckets(self._email_buckets)
        for w in self._ip_buckets.values():
            w._prune(now)
        self._sweep_empty_buckets(self._ip_buckets)

    def retry_after(self, email: str, client_ip: str, now: float | None = None) -> float:
        """Return the *Retry-After* value in seconds for the narrow tier, or ``0.0``."""
        hashed = self._hash_key(self._normalize_email(email), client_ip)
        bucket = self._email_buckets.get(hashed)
        if bucket is None:
            return 0.0
        result = bucket.retry_after(now)
        self._remove_if_empty(self._email_buckets, hashed)
        return result

    @staticmethod
    def get_client_ip(request: Request, trusted_proxies: str = "") -> str:
        """Extract the originating client IP from a request.

        *X-Forwarded-For* headers are **only** trusted when one or more
        ``trusted_proxies`` are configured.  Otherwise the direct peer
        IP (``request.client.host``) is used, which is safe when the
        application is fronted by a known reverse proxy.

        When ``trusted_proxies`` is set, the header is parsed **right-to-left**.
        Each proxy hop APPENDS the IP it observed to the right end, so entries
        to the left of the first untrusted entry are fully attacker-controlled
        and must be ignored.  The trustworthy client IP is the first entry
        counting FROM THE RIGHT that is not a trusted proxy.  If every entry
        is a trusted proxy (or the header is empty/absent, or
        ``trusted_proxies`` is unset), fall back to ``request.client.host``.
        """
        if trusted_proxies:
            forwarded = request.headers.get("X-Forwarded-For", "")
            if forwarded:
                proxies = {p.strip() for p in trusted_proxies.split(",")}
                # Walk right-to-left: the rightmost untrusted IP is the real
                # client.  Entries left of it are attacker-controlled spoofs.
                ips = [ip.strip() for ip in forwarded.split(",")]
                for ip in reversed(ips):
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
