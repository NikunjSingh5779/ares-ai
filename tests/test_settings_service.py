"""Tests for the durable dashboard-preferences store."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from backend.schemas.settings import DashboardPreferences
from backend.services import settings_service


class _Result:
    """Minimal SQLAlchemy result stand-in for the one-row settings query."""

    def __init__(self, value: Any = None, *, has_row: bool = True) -> None:
        self._value = value
        self._has_row = has_row

    def first(self) -> tuple[Any] | None:
        return (self._value,) if self._has_row else None


def _session(result: _Result) -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)
    return session


def test_decode_merges_stored_values_over_defaults() -> None:
    preferences = settings_service._decode_preferences({"default_symbol": "ETH-USD"})

    assert preferences.default_symbol == "ETH-USD"
    assert preferences.live_refresh_seconds == DashboardPreferences().live_refresh_seconds


def test_decode_accepts_a_json_string_from_the_driver() -> None:
    preferences = settings_service._decode_preferences(
        json.dumps({"default_symbol": "SOL-USD", "live_refresh_seconds": 15})
    )

    assert preferences.default_symbol == "SOL-USD"
    assert preferences.live_refresh_seconds == 15


@pytest.mark.parametrize(
    "value",
    [
        None,
        "not-json",
        ["not", "an", "object"],
        {"default_symbol": "bad symbol"},
        {"live_refresh_seconds": 1},
    ],
)
def test_decode_falls_back_to_defaults_for_invalid_storage(value: Any) -> None:
    preferences = settings_service._decode_preferences(value)

    assert preferences == DashboardPreferences()


async def test_load_returns_defaults_when_no_row_exists() -> None:
    session = _session(_Result(has_row=False))

    preferences = await settings_service.load_preferences(session)

    assert preferences == DashboardPreferences()
    session.execute.assert_awaited_once()


async def test_load_returns_validated_row() -> None:
    session = _session(_Result({"default_symbol": "ETH-USD", "live_refresh_seconds": 10}))

    preferences = await settings_service.load_preferences(session)

    assert preferences.default_symbol == "ETH-USD"
    assert preferences.live_refresh_seconds == 10


async def test_save_upserts_and_returns_the_accepted_value() -> None:
    session = _session(_Result({"default_symbol": "ETH-USD", "live_refresh_seconds": 10}))
    requested = DashboardPreferences(default_symbol="eth-usd", live_refresh_seconds=10)

    preferences = await settings_service.save_preferences(session, requested)

    assert preferences.default_symbol == "ETH-USD"
    assert preferences.live_refresh_seconds == 10
    statement, params = session.execute.await_args.args
    assert "INSERT INTO app_settings" in str(statement)
    assert "ON CONFLICT (id) DO UPDATE" in str(statement)
    assert json.loads(params["preferences"]) == {
        "default_symbol": "ETH-USD",
        "live_refresh_seconds": 10,
    }


async def test_save_raises_when_postgres_returns_no_row() -> None:
    session = _session(_Result(has_row=False))

    with pytest.raises(RuntimeError, match="Settings upsert returned no row"):
        await settings_service.save_preferences(session, DashboardPreferences())
