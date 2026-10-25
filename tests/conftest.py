"""Shared test fixtures.

The application requires a credential on every non-public route and a role on
trading/live-control routes. Most tests exercise domain behaviour rather than
auth, so this autouse fixture overrides the auth and role dependencies for the
shared ``backend.main`` app. Dedicated security tests clear the overrides and
exercise the real gates.
"""

from __future__ import annotations

import pytest

from backend.core.dependencies import (
    AuthPrincipal,
    require_live_control,
    require_trading_access,
    verify_auth,
)
from backend.main import app

_TEST_PRINCIPAL = AuthPrincipal(subject="test-user-id", role="admin")


@pytest.fixture(autouse=True)
def _bypass_api_auth_for_domain_tests():
    """Authenticate domain tests without weakening the production gates."""
    app.dependency_overrides[verify_auth] = lambda: "test-user-id"
    app.dependency_overrides[require_trading_access] = lambda: _TEST_PRINCIPAL
    app.dependency_overrides[require_live_control] = lambda: _TEST_PRINCIPAL
    yield
    for dependency in (verify_auth, require_trading_access, require_live_control):
        app.dependency_overrides.pop(dependency, None)
