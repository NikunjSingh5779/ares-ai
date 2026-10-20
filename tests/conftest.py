"""Shared test fixtures.

The application now requires a credential on every non-public route. Most
tests exercise domain behaviour rather than auth, so this autouse fixture
overrides the ``verify_auth`` dependency for the shared ``backend.main`` app.
Dedicated auth tests (``tests/test_security/test_auth.py`` and
``test_route_auth.py``) clear the override and exercise the real dependency.
"""

from __future__ import annotations

import pytest

from backend.core.dependencies import verify_auth
from backend.main import app


@pytest.fixture(autouse=True)
def _bypass_api_auth_for_domain_tests():
    """Authenticate domain tests without weakening the production gate."""
    app.dependency_overrides[verify_auth] = lambda: "test-user-id"
    yield
    app.dependency_overrides.pop(verify_auth, None)
