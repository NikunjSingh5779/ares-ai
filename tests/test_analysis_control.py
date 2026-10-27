"""Tests for analysis concurrency, run budget, and per-session state control."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator

import pytest

from agents.state import AgentState, PipelineStatus
from backend.services.analysis_control import (
    AnalysisBudgetExceededError,
    AnalysisBusyError,
    AnalysisGate,
    AnalysisLease,
    AnalysisStateStore,
    get_analysis_gate,
    get_analysis_state_store,
    reset_analysis_control,
)
from configs.settings import settings


def _state(session_id: str = "session-1", symbol: str = "BTC-USD") -> AgentState:
    return AgentState(
        symbol=symbol,
        request="Analyze",
        request_id=f"req-{session_id}",
        session_id=session_id,
        pipeline_status=PipelineStatus(current_node="supervisor"),
    )


@pytest.fixture(autouse=True)
def _reset_control() -> Iterator[None]:
    """Keep the process-wide gate and store isolated between tests."""
    reset_analysis_control()
    yield
    reset_analysis_control()


class TestAnalysisStateStore:
    """The store replaces the single module-global ``_last_state``."""

    def test_put_and_get_by_session(self) -> None:
        store = AnalysisStateStore(max_entries=4)
        first = _state("first")
        second = _state("second")

        store.put(first, make_latest=True)
        store.put(second, make_latest=True)

        assert store.get("first") is first
        assert store.get("second") is second
        assert store.latest() is second
        assert store.latest_session_id() == "second"
        assert len(store) == 2

    def test_older_run_update_does_not_steal_latest(self) -> None:
        store = AnalysisStateStore(max_entries=4)
        first = _state("first")
        second = _state("second")
        store.put(first, make_latest=True)
        store.put(second, make_latest=True)

        updated_first = first.model_copy(update={"request": "updated"})
        store.put(updated_first)

        assert store.get("first") is updated_first
        assert store.latest() is second

    def test_evicts_oldest_entry(self) -> None:
        store = AnalysisStateStore(max_entries=2)
        store.put(_state("a"), make_latest=True)
        store.put(_state("b"), make_latest=True)
        store.put(_state("c"), make_latest=True)

        assert store.get("a") is None
        assert store.get("b") is not None
        assert store.get("c") is not None
        assert store.latest_session_id() == "c"
        assert len(store) == 2

    def test_eviction_uses_start_order_not_update_order(self) -> None:
        """A late update from an older run must not evict a newer run."""
        store = AnalysisStateStore(max_entries=2)
        first = _state("first")
        store.put(first, make_latest=True)
        store.put(_state("second"), make_latest=True)

        store.put(first.model_copy(update={"request": "late update"}))
        store.put(_state("third"), make_latest=True)

        assert store.get("first") is None
        assert store.get("second") is not None
        assert store.get("third") is not None
        assert store.latest_session_id() == "third"

    def test_evicting_latest_moves_latest_to_remaining_entry(self) -> None:
        store = AnalysisStateStore(max_entries=1)
        store.put(_state("a"), make_latest=True)
        store.put(_state("b"))

        assert store.get("a") is None
        assert store.latest_session_id() == "b"
        assert store.latest() is not None

    def test_requires_session_id(self) -> None:
        store = AnalysisStateStore()
        with pytest.raises(ValueError, match="session_id"):
            store.put(_state(""))

    def test_rejects_non_positive_capacity(self) -> None:
        with pytest.raises(ValueError, match="max_entries"):
            AnalysisStateStore(max_entries=0)

    def test_clear_removes_everything(self) -> None:
        store = AnalysisStateStore()
        store.put(_state("a"), make_latest=True)
        store.clear()

        assert store.latest() is None
        assert store.latest_session_id() is None
        assert len(store) == 0


class TestAnalysisGate:
    """The gate bounds concurrent runs and enforces the rolling run budget."""

    @pytest.mark.asyncio
    async def test_try_start_rejects_when_full(self) -> None:
        gate = AnalysisGate(max_concurrent=1)
        lease = await gate.try_start()
        assert gate.in_use == 1

        with pytest.raises(AnalysisBusyError) as exc_info:
            await gate.try_start()

        assert exc_info.value.retry_after_seconds == 1
        lease.release()
        assert gate.in_use == 0

    @pytest.mark.asyncio
    async def test_lease_release_is_idempotent(self) -> None:
        gate = AnalysisGate(max_concurrent=1)
        lease = await gate.try_start()
        lease.release()
        lease.release()

        assert lease.released is True
        assert gate.in_use == 0

    @pytest.mark.asyncio
    async def test_acquire_times_out_when_full(self) -> None:
        gate = AnalysisGate(max_concurrent=1, queue_timeout_seconds=0.01)
        lease = await gate.try_start()

        with pytest.raises(AnalysisBusyError) as exc_info:
            await gate.acquire()

        assert exc_info.value.queue_timeout_seconds == 0.01
        lease.release()

    @pytest.mark.asyncio
    async def test_budget_rejects_after_limit(self) -> None:
        gate = AnalysisGate(max_concurrent=2, max_runs_per_window=1)
        lease = await gate.try_start()
        lease.release()

        with pytest.raises(AnalysisBudgetExceededError) as exc_info:
            await gate.try_start()

        assert exc_info.value.retry_after_seconds >= 1
        assert gate.budget_remaining == 0

    @pytest.mark.asyncio
    async def test_budget_window_expires(self) -> None:
        gate = AnalysisGate(max_concurrent=1, max_runs_per_window=1, budget_window_seconds=0.02)
        lease = await gate.try_start()
        lease.release()

        await asyncio.sleep(0.05)
        lease = await gate.try_start()
        lease.release()

        assert gate.budget_remaining == 0

    @pytest.mark.asyncio
    async def test_budget_is_not_consumed_by_a_busy_rejection(self) -> None:
        gate = AnalysisGate(max_concurrent=1, max_runs_per_window=2)
        lease = await gate.try_start()

        with pytest.raises(AnalysisBusyError):
            await gate.try_start()

        lease.release()
        # The busy rejection did not consume a second timestamp, so the next
        # start is still inside the two-run budget.
        lease = await gate.try_start()
        assert gate.budget_remaining == 0
        lease.release()

        with pytest.raises(AnalysisBudgetExceededError):
            await gate.try_start()

    @pytest.mark.asyncio
    async def test_queued_acquire_rechecks_budget_after_waiting(self) -> None:
        """Queued /signal callers must not all start after one budget check."""
        gate = AnalysisGate(max_concurrent=1, max_runs_per_window=2, queue_timeout_seconds=1.0)
        first = await gate.try_start()

        async def run_waiter() -> None:
            lease = await gate.acquire()
            lease.release()

        waiters = [asyncio.create_task(run_waiter()) for _ in range(3)]
        await asyncio.sleep(0)
        first.release()
        results = await asyncio.gather(*waiters, return_exceptions=True)

        successes = [result for result in results if result is None]
        budget_errors = [result for result in results if isinstance(result, AnalysisBudgetExceededError)]
        assert len(successes) == 1
        assert len(budget_errors) == 2
        assert gate.in_use == 0
        assert gate.budget_remaining == 0

    def test_release_without_acquire_raises(self) -> None:
        gate = AnalysisGate()
        with pytest.raises(RuntimeError, match="without a matching acquire"):
            gate.release()

    def test_lease_release_without_acquire_raises(self) -> None:
        gate = AnalysisGate()
        lease = AnalysisLease(gate)
        with pytest.raises(RuntimeError, match="without a matching acquire"):
            lease.release()

    def test_rejects_invalid_limits(self) -> None:
        with pytest.raises(ValueError, match="max_concurrent"):
            AnalysisGate(max_concurrent=0)
        with pytest.raises(ValueError, match="timeout_seconds"):
            AnalysisGate(timeout_seconds=0)
        with pytest.raises(ValueError, match="max_runs_per_window"):
            AnalysisGate(max_runs_per_window=0)
        with pytest.raises(ValueError, match="queue_timeout_seconds"):
            AnalysisGate(queue_timeout_seconds=0)
        with pytest.raises(ValueError, match="budget_window_seconds"):
            AnalysisGate(budget_window_seconds=0)

    def test_singletons_follow_settings(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(settings, "analysis_max_concurrent", 3)
        monkeypatch.setattr(settings, "analysis_timeout_seconds", 42.0)
        monkeypatch.setattr(settings, "analysis_max_runs_per_hour", 7)
        monkeypatch.setattr(settings, "analysis_queue_timeout_seconds", 1.5)
        monkeypatch.setattr(settings, "analysis_state_cache_size", 9)
        reset_analysis_control()

        gate = get_analysis_gate()
        store = get_analysis_state_store()

        assert gate.max_concurrent == 3
        assert gate.timeout_seconds == 42.0
        assert gate.max_runs_per_window == 7
        assert gate.queue_timeout_seconds == 1.5
        assert store.max_entries == 9
