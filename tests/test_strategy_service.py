"""Tests for the draft-strategy persistence service."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from backend.schemas.strategy import (
    StrategyConfig,
    StrategyCreate,
    StrategyParameters,
    StrategyUpdate,
)
from backend.services import strategy_service

NOW = datetime.now(UTC)


def _row(
    *,
    row_id: Any | None = None,
    name: str = "Momentum Draft",
    description: str = "Trend following draft",
    strategy_type: str = "momentum",
    config: Any | None = None,
    parameters: Any | None = None,
    version: int = 1,
    status: str = "draft",
    created_at: datetime = NOW,
    updated_at: datetime | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=row_id or uuid4(),
        name=name,
        description=description,
        strategy_type=strategy_type,
        config=config if config is not None else {"indicators": ["sma", "rsi"]},
        parameters=parameters
        if parameters is not None
        else {"position_size_pct": 10, "stop_loss_pct": 5, "take_profit_pct": 15},
        version=version,
        status=status,
        paper_trade_closed_trades=0,
        live_trading_enabled=False,
        created_at=created_at,
        updated_at=updated_at or created_at + timedelta(minutes=1),
    )


class _Result:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows or []

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Any]:
        return self._rows


def _session(*results: _Result) -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock(side_effect=list(results))
    return session


def test_decode_json_accepts_a_driver_string_and_rejects_garbage() -> None:
    assert strategy_service._decode_json('{"indicators": ["ema"]}') == {"indicators": ["ema"]}
    assert strategy_service._decode_json("not-json") == {}
    assert strategy_service._decode_json(None) == {}


def test_row_to_response_parses_json_and_server_owned_fields() -> None:
    row = _row(config='{"indicators": ["ema"]}', parameters='{"position_size_pct": 7}')

    response = strategy_service._row_to_response(row)

    assert response.name == "Momentum Draft"
    assert response.config.indicators == ["ema"]
    assert response.parameters.position_size_pct == 7
    assert response.parameters.stop_loss_pct == 5
    assert response.status == "draft"
    assert response.live_trading_enabled is False


async def test_list_returns_newest_first_rows() -> None:
    first = _row(name="First")
    second = _row(name="Second")
    session = _session(_Result([first, second]))

    strategies = await strategy_service.list_strategies(session, limit=10)

    assert [item.name for item in strategies] == ["First", "Second"]
    statement, params = session.execute.await_args.args
    assert "ORDER BY updated_at DESC" in str(statement)
    assert params == {"limit": 10}


async def test_list_clamps_the_limit() -> None:
    session = _session(_Result([]))

    await strategy_service.list_strategies(session, limit=500)

    assert session.execute.await_args.args[1] == {"limit": 100}


async def test_get_returns_none_when_missing() -> None:
    session = _session(_Result([]))

    assert await strategy_service.get_strategy(session, uuid4()) is None


async def test_create_inserts_a_draft_and_returns_the_row() -> None:
    row = _row()
    session = _session(_Result([row]))
    payload = StrategyCreate(
        name="  Momentum Draft  ",
        description="  Trend following draft  ",
        strategy_type="momentum",
        config=StrategyConfig(indicators=["SMA", "rsi", "sma"]),
        parameters=StrategyParameters(position_size_pct=10),
    )

    created = await strategy_service.create_strategy(session, payload)

    assert created.name == "Momentum Draft"
    statement, params = session.execute.await_args.args
    assert "INSERT INTO strategies" in str(statement)
    assert params["name"] == "Momentum Draft"
    assert params["strategy_type"] == "momentum"
    assert json.loads(params["config"]) == {"indicators": ["sma", "rsi"]}
    assert "status" not in params
    assert "live_trading_enabled" not in params


async def test_create_raises_when_postgres_returns_no_row() -> None:
    session = _session(_Result([]))

    with pytest.raises(RuntimeError, match="Strategy insert returned no row"):
        await strategy_service.create_strategy(
            session,
            StrategyCreate(name="Empty", strategy_type="custom"),
        )


async def test_update_merges_fields_and_bumps_the_version() -> None:
    strategy_id = uuid4()
    current = _row(row_id=strategy_id, version=1)
    updated = _row(
        row_id=strategy_id,
        name="Momentum v2",
        version=2,
        updated_at=NOW + timedelta(minutes=2),
    )
    session = _session(_Result([current]), _Result([updated]))

    result = await strategy_service.update_strategy(
        session,
        strategy_id,
        StrategyUpdate(name=" Momentum v2 "),
    )

    assert result.name == "Momentum v2"
    assert result.version == 2
    statement, params = session.execute.await_args.args
    assert "version = version + 1" in str(statement)
    assert params["name"] == "Momentum v2"
    assert json.loads(params["config"]) == {"indicators": ["sma", "rsi"]}
    assert json.loads(params["parameters"]) == {
        "position_size_pct": 10,
        "stop_loss_pct": 5,
        "take_profit_pct": 15,
    }


async def test_update_rejects_a_non_draft_strategy() -> None:
    session = _session(_Result([_row(status="paper_trading")]))

    with pytest.raises(strategy_service.StrategyNotEditableError):
        await strategy_service.update_strategy(
            session,
            uuid4(),
            StrategyUpdate(name="Nope"),
        )


async def test_update_raises_when_the_row_disappears() -> None:
    strategy_id = uuid4()
    session = _session(
        _Result([_row(row_id=strategy_id)]),
        _Result([]),
        _Result([]),
    )

    with pytest.raises(strategy_service.StrategyNotFoundError):
        await strategy_service.update_strategy(
            session,
            strategy_id,
            StrategyUpdate(name="Gone"),
        )


async def test_update_fails_closed_if_the_status_changes_during_the_write() -> None:
    strategy_id = uuid4()
    session = _session(
        _Result([_row(row_id=strategy_id, status="draft")]),
        _Result([]),
        _Result([_row(row_id=strategy_id, status="paper_trading")]),
    )

    with pytest.raises(strategy_service.StrategyNotEditableError):
        await strategy_service.update_strategy(
            session,
            strategy_id,
            StrategyUpdate(name="Too late"),
        )
