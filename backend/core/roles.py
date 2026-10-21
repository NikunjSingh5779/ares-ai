"""Role hierarchy for trading and live-control authorization.

The database stores one of four roles:

* ``viewer`` — read-only; cannot execute a trade or touch live controls.
* ``operator`` — may paper-trade and operate the live controls.
* ``admin`` / ``super_admin`` — operator rights plus user administration.

``user`` is the pre-P1.6 default. Migration ``0004`` rewrites it to
``operator`` and ``normalize_role`` maps it for tokens issued before the
migration. Unknown values fail closed to ``viewer``.
"""

from __future__ import annotations

VIEWER = "viewer"
OPERATOR = "operator"
ADMIN = "admin"
SUPER_ADMIN = "super_admin"

VALID_ROLES: frozenset[str] = frozenset({VIEWER, OPERATOR, ADMIN, SUPER_ADMIN})

# Any role below may execute a paper trade or operate a live control.
TRADING_ROLES: frozenset[str] = frozenset({OPERATOR, ADMIN, SUPER_ADMIN})
LIVE_CONTROL_ROLES: frozenset[str] = TRADING_ROLES

# User-administration routes require one of these.
ADMIN_ROLES: frozenset[str] = frozenset({ADMIN, SUPER_ADMIN})

_LEGACY_ALIASES: dict[str, str] = {"user": OPERATOR}


def normalize_role(role: str) -> str:
    """Return a valid role, mapping the legacy ``user`` value and failing closed."""
    normalized = _LEGACY_ALIASES.get(role, role)
    return normalized if normalized in VALID_ROLES else VIEWER
