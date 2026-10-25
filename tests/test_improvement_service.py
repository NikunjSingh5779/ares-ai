"""Tests for durable improvement-history persistence."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agents.improvement import StrategyImprovementEngine
from agents.state import AgentState, ReflectionOutput
from backend.services import improvement_service

NOW = datetime.now(UTC)
RUN_ID = uuid4()


class _Result:
    def __init__(self, rows: list[Any] | None = None) -> None:
        self._rows = rows or []

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def fetchall(self) -> list[Any]:
        return self._rows


class _Factory:
    """Minimal async context manager that yields one fake session."""

    def __init__(self, session: Any) -> None:
        self.session = session

    def __call__(self) -> _Factory:
        return self

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, *exc: object) -> bool:
        return False


def _history_row(
    *,
    executed: bool = True,
    accuracy: float = 85.0,
    suggestions: list[str] | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        evaluation="Trade executed: long at $100" if executed else "Trade not executed: no consensus",
        confidence_accuracy=accuracy,
        improvement_suggestions=suggestions or [],
    )


def _record_row(**overrides: Any) -> SimpleNamespace:
    values: dict[str, Any] = {
        "id": uuid4(),
        "created_at": NOW,
        "category": "risk_calibration",
        "description": "Execution rate declined",
        "severity": "high",
        "metric_before": 80.0,
        "metric_after": 40.0,
        "applied": False,
        "rationale": "Review risk thresholds",
        "suggested_params": {"max_drawdown_pct": 15.0},
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _session(results: list[_Result]) -> MagicMock:
    session = MagicMock()
    session.execute = AsyncMock(side_effect=list(results))
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _session_with_dispatch(history_rows: list[SimpleNamespace]) -> MagicMock:
    """Fake session that answers the three statements record_and_analyze issues."""

    async def _execute(statement: Any, params: dict[str, Any] | None = None) -> _Result:
        sql = str(statement)
        if "INSERT INTO reflection_runs" in sql:
            return _Result([SimpleNamespace(id=RUN_ID)])
        if "FROM reflection_runs" in sql:
            return _Result(history_rows)
        if "INSERT INTO improvement_records" in sql:
            assert params is not None
            return _Result([SimpleNamespace(id=params["id"])])
        raise AssertionError(f"Unexpected SQL: {sql}")

    session = MagicMock()
    session.execute = AsyncMock(side_effect=_execute)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


def _reflection(**overrides: Any) -> dict[str, Any]:
    values: dict[str, Any] = {
        "evaluation": "Trade executed: long at $100",
        "confidence_accuracy": 80.0,
        "improvement_suggestions": [],
        "knowledge_updates": ["Keep watching"],
    }
    values.update(overrides)
    return values


async def test_record_and_analyze_persists_the_run_and_reads_prior_history() -> None:
    session = _session_with_dispatch([_history_row() for _ in range(4)])
    request_id = uuid4()
    session_id = uuid4()

    summary = await improvement_service.record_and_analyze(
        _reflection(improvement_suggestions=["Review entry timing"]),
        symbol="BTC-USD",
        request_id=str(request_id),
        session_id=str(session_id),
        errors=[{"agent": "news", "error": "timeout"}],
        session_factory=_Factory(session),  # type: ignore[arg-type]
        engine=StrategyImprovementEngine(),
    )

    assert summary.reflection_run_id == RUN_ID
    assert summary.metrics["total_runs"] == 5
    assert summary.records == []
    session.commit.assert_awaited_once()
    session.rollback.assert_not_awaited()

    insert_call = session.execute.await_args_list[0]
    params = insert_call.args[1]
    assert params["symbol"] == "BTC-USD"
    assert params["request_id"] == request_id
    assert params["session_id"] == session_id
    assert json.loads(params["improvement_suggestions"]) == ["Review entry timing"]
    assert json.loads(params["knowledge_updates"]) == ["Keep watching"]
    assert json.loads(params["errors"]) == [{"agent": "news", "error": "timeout"}]

    history_call = session.execute.await_args_list[1]
    assert history_call.args[1]["run_id"] == RUN_ID


async def test_record_and_analyze_persists_generated_records() -> None:
    history = [_history_row(executed=True) for _ in range(9)]
    history[-4:] = [
        _history_row(executed=True),
        _history_row(executed=True),
        _history_row(executed=False),
        _history_row(executed=False),
    ]
    session = _session_with_dispatch(history)

    summary = await improvement_service.record_and_analyze(
        _reflection(evaluation="Trade not executed: no consensus"),
        symbol="ETH-USD",
        session_factory=_Factory(session),  # type: ignore[arg-type]
        engine=StrategyImprovementEngine(),
    )

    assert [record.category for record in summary.records] == ["risk_calibration"]
    record_call = session.execute.await_args_list[-1]
    params = record_call.args[1]
    assert params["reflection_run_id"] == RUN_ID
    assert params["category"] == "risk_calibration"
    assert params["suggested_params"] == json.dumps({"max_drawdown_pct": 15.0})
    session.commit.assert_awaited_once()


async def test_record_and_analyze_rolls_back_on_write_failure() -> None:
    session = MagicMock()
    session.execute = AsyncMock(side_effect=RuntimeError("database down"))
    session.commit = AsyncMock()
    session.rollback = AsyncMock()

    with pytest.raises(RuntimeError, match="database down"):
        await improvement_service.record_and_analyze(
            _reflection(),
            session_factory=_Factory(session),  # type: ignore[arg-type]
        )

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()


async def test_list_records_maps_rows_and_clamps_the_limit() -> None:
    row = _record_row(suggested_params='{"max_drawdown_pct": 15.0}')
    session = _session([_Result([row])])

    records = await improvement_service.list_records(session, limit=500)

    assert records[0]["id"] == str(row.id)
    assert records[0]["timestamp"] == NOW.isoformat()
    assert records[0]["suggested_params"] == {"max_drawdown_pct": 15.0}
    assert records[0]["applied"] is False
    assert session.execute.await_args.args[1] == {"limit": 100}


async def test_apply_record_rejects_a_malformed_id_without_querying() -> None:
    session = MagicMock()
    session.execute = AsyncMock()

    assert await improvement_service.apply_record(session, "not-a-uuid") is False
    session.execute.assert_not_awaited()


async def test_apply_record_returns_true_when_the_row_is_updated() -> None:
    session = _session([_Result([SimpleNamespace(id=uuid4())])])

    assert await improvement_service.apply_record(session, str(uuid4())) is True


async def test_apply_record_returns_false_when_the_row_is_missing() -> None:
    session = _session([_Result([])])

    assert await improvement_service.apply_record(session, str(uuid4())) is False


async def test_metrics_reads_history_and_returns_aggregates() -> None:
    rows = [_history_row(executed=True, accuracy=80.0) for _ in range(5)]
    session = _session([_Result(rows)])

    result = await improvement_service.metrics(session)

    assert result["total_runs"] == 5
    assert result["execution_rate"] == 100.0
    assert result["avg_confidence_accuracy"] == 80.0


async def test_record_reflection_improvement_skips_without_reflection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = AsyncMock()
    monkeypatch.setattr(improvement_service, "record_and_analyze", mock)

    await improvement_service.record_reflection_improvement(AgentState(symbol="BTC-USD"))

    mock.assert_not_awaited()


async def test_record_reflection_improvement_passes_state_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = AsyncMock()
    monkeypatch.setattr(improvement_service, "record_and_analyze", mock)
    state = AgentState(
        symbol="BTC-USD",
        request_id=str(uuid4()),
        session_id=str(uuid4()),
        reflection=ReflectionOutput(
            evaluation="Trade executed: long at $100",
            confidence_accuracy=82.0,
            improvement_suggestions=["Review entry timing"],
            knowledge_updates=[],
        ),
    )

    await improvement_service.record_reflection_improvement(state)

    assert mock.await_args is not None
    args, kwargs = mock.await_args
    assert args[0]["evaluation"] == "Trade executed: long at $100"
    assert kwargs["symbol"] == "BTC-USD"
    assert kwargs["request_id"] == state.request_id
    assert kwargs["session_id"] == state.session_id


async def test_record_reflection_improvement_swallows_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    mock = AsyncMock(side_effect=RuntimeError("database down"))
    monkeypatch.setattr(improvement_service, "record_and_analyze", mock)
    state = AgentState(
        symbol="BTC-USD",
        reflection=ReflectionOutput(
            evaluation="Trade executed: long at $100",
            confidence_accuracy=82.0,
            improvement_suggestions=[],
            knowledge_updates=[],
        ),
    )

    await improvement_service.record_reflection_improvement(state)

    mock.assert_awaited_once()
