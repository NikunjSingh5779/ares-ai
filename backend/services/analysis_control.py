"""Concurrency, timeout, and run-budget control for the analysis pipeline.

Every analysis run can make many LLM requests, and the pipeline includes a
paper-execution node.  This module owns the process-wide controls that keep a
burst of ``/analyze`` calls from turning into an unbounded number of
background pipelines:

* at most ``analysis_max_concurrent`` pipelines run at once;
* a caller that cannot get a slot within ``analysis_queue_timeout_seconds``
  fails closed instead of waiting forever;
* a rolling window caps how many runs may start per hour.  On the free tier
  the run count is the meaningful unit of model spend, so this is the cost
  budget;
* every accepted run has an ``analysis_timeout_seconds`` stage-start deadline;
  the slot is released on success, failure, timeout, or cancellation.

The state store is keyed by ``session_id`` instead of one module-global
``_last_state``.  The dashboard still reads the most recently started session;
API callers can read a specific run with the ``session_id`` returned by
``POST /analyze``.

All controls are process-local, matching the rest of the API (Prometheus
counters, the local-model gate, and the in-memory paper cache).  A multi-worker
deployment would need a shared store such as Redis; the current Compose stack
runs one uvicorn worker.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import OrderedDict, deque

from agents.state import AgentState
from backend.core.metrics import set_analysis_in_flight


class AnalysisBusyError(RuntimeError):
    """No analysis slot opened within the configured queue timeout."""

    def __init__(self, max_concurrent: int, queue_timeout_seconds: float | None = None) -> None:
        self.max_concurrent = max_concurrent
        self.queue_timeout_seconds = queue_timeout_seconds
        self.retry_after_seconds = 1
        if queue_timeout_seconds is None:
            message = f"Analysis pipeline is busy ({max_concurrent} run(s) in flight); retry shortly"
        else:
            message = f"Analysis pipeline is busy; no slot opened within {queue_timeout_seconds:.1f}s"
        super().__init__(message)


class AnalysisBudgetExceededError(RuntimeError):
    """The rolling run budget for the analysis pipeline is exhausted."""

    def __init__(self, retry_after_seconds: int) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(f"Analysis run budget exhausted; retry in {retry_after_seconds}s")


class AnalysisLease:
    """Idempotent handle for one acquired analysis slot.

    The router holds a lease for the whole lifetime of a background task or an
    SSE response.  Releasing twice is safe, so both the generator and the
    response wrapper can release without leaking or double-releasing the
    underlying semaphore.
    """

    def __init__(self, gate: AnalysisGate) -> None:
        self._gate = gate
        self._released = False

    def release(self) -> None:
        """Release the slot exactly once."""
        if not self._released:
            self._released = True
            self._gate.release()

    @property
    def released(self) -> bool:
        """Whether this lease has already released its slot."""
        return self._released


class AnalysisStateStore:
    """Bounded, per-session store for the most recent analysis states.

    ``latest()`` follows the most recently *started* run, not the most recent
    update.  That preserves the dashboard contract (a new trigger immediately
    becomes the visible run) while a slower, older run can still update its own
    session without stealing the display.
    """

    def __init__(self, max_entries: int = 64) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be at least 1")
        self.max_entries = max_entries
        self._states: OrderedDict[str, AgentState] = OrderedDict()
        self._latest_session_id: str | None = None

    def put(self, state: AgentState, *, make_latest: bool = False) -> None:
        """Store ``state`` under its session id, evicting the oldest start.

        An update to an existing session keeps its original start position, so
        a late update from an older run cannot evict a newer run when the
        cache is small.
        """
        session_id = state.session_id
        if not session_id:
            raise ValueError("state.session_id is required")
        self._states[session_id] = state
        if make_latest or self._latest_session_id is None:
            self._latest_session_id = session_id
        while len(self._states) > self.max_entries:
            evicted, _ = self._states.popitem(last=False)
            if evicted == self._latest_session_id:
                self._latest_session_id = next(reversed(self._states), None)

    def get(self, session_id: str) -> AgentState | None:
        """Return one session's state, or ``None`` when it has been evicted."""
        return self._states.get(session_id)

    def latest(self) -> AgentState | None:
        """Return the most recently started run that is still retained."""
        if self._latest_session_id is None:
            return None
        return self._states.get(self._latest_session_id)

    def latest_session_id(self) -> str | None:
        """Return the session id selected by :meth:`latest`."""
        return self._latest_session_id

    def clear(self) -> None:
        """Drop every retained state (tests and shutdown)."""
        self._states.clear()
        self._latest_session_id = None

    def __len__(self) -> int:
        return len(self._states)


class AnalysisGate:
    """Process-wide concurrency semaphore plus a rolling run budget.

    The semaphore is created per event loop, following ``LocalModelGate``;
    tests build a fresh loop per test, while production uses one loop for the
    life of the process.
    """

    def __init__(
        self,
        max_concurrent: int = 1,
        timeout_seconds: float = 300.0,
        max_runs_per_window: int = 30,
        queue_timeout_seconds: float = 5.0,
        budget_window_seconds: float = 3600.0,
    ) -> None:
        if max_concurrent < 1:
            raise ValueError("max_concurrent must be at least 1")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if max_runs_per_window < 1:
            raise ValueError("max_runs_per_window must be at least 1")
        if queue_timeout_seconds <= 0:
            raise ValueError("queue_timeout_seconds must be positive")
        if budget_window_seconds <= 0:
            raise ValueError("budget_window_seconds must be positive")
        self.max_concurrent = max_concurrent
        self.timeout_seconds = timeout_seconds
        self.max_runs_per_window = max_runs_per_window
        self.queue_timeout_seconds = queue_timeout_seconds
        self.budget_window_seconds = budget_window_seconds
        self._semaphore: asyncio.Semaphore | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._in_use = 0
        self._run_times: deque[float] = deque()

    def _semaphore_for_current_loop(self) -> asyncio.Semaphore:
        loop = asyncio.get_running_loop()
        if self._semaphore is None or self._loop is not loop:
            self._semaphore = asyncio.Semaphore(self.max_concurrent)
            self._loop = loop
            self._in_use = 0
        return self._semaphore

    def _prune_budget(self, now: float) -> None:
        cutoff = now - self.budget_window_seconds
        while self._run_times and self._run_times[0] <= cutoff:
            self._run_times.popleft()

    def _check_budget(self) -> None:
        now = time.monotonic()
        self._prune_budget(now)
        if len(self._run_times) >= self.max_runs_per_window:
            oldest = self._run_times[0]
            retry_after = max(1, math.ceil(oldest + self.budget_window_seconds - now))
            raise AnalysisBudgetExceededError(retry_after)

    def _record_start(self) -> None:
        self._run_times.append(time.monotonic())
        set_analysis_in_flight(self._in_use)

    async def try_start(self) -> AnalysisLease:
        """Acquire a slot without waiting; raise when busy or over budget.

        This is the path used by the background and streaming endpoints: the
        caller gets an immediate ``429`` rather than a queued task that might
        start minutes later.
        """
        self._check_budget()
        semaphore = self._semaphore_for_current_loop()
        if semaphore.locked():
            raise AnalysisBusyError(self.max_concurrent)
        # Acquiring an unlocked semaphore does not suspend, so the check and
        # the acquire are atomic within the event loop.
        await semaphore.acquire()
        self._in_use += 1
        self._record_start()
        return AnalysisLease(self)

    async def acquire(self) -> AnalysisLease:
        """Wait up to ``queue_timeout_seconds`` for a slot, then fail closed.

        The budget is checked again after the wait.  Without the second check,
        every queued ``/signal`` caller would pass the admission check while
        the budget still had room and then all start together when a slot
        opened.
        """
        self._check_budget()
        semaphore = self._semaphore_for_current_loop()
        try:
            await asyncio.wait_for(semaphore.acquire(), timeout=self.queue_timeout_seconds)
        except TimeoutError as exc:
            raise AnalysisBusyError(self.max_concurrent, self.queue_timeout_seconds) from exc
        try:
            self._check_budget()
        except AnalysisBudgetExceededError:
            semaphore.release()
            raise
        self._in_use += 1
        self._record_start()
        return AnalysisLease(self)

    def release(self) -> None:
        """Release a slot acquired by :meth:`try_start` or :meth:`acquire`."""
        if self._semaphore is None or self._in_use <= 0:
            raise RuntimeError("Analysis gate released without a matching acquire")
        self._in_use -= 1
        self._semaphore.release()
        set_analysis_in_flight(self._in_use)

    @property
    def in_use(self) -> int:
        """Number of slots currently held (process-local diagnostic)."""
        return self._in_use

    @property
    def budget_remaining(self) -> int:
        """Runs that may still start in the current rolling window."""
        self._prune_budget(time.monotonic())
        return max(0, self.max_runs_per_window - len(self._run_times))

    def reset(self) -> None:
        """Drop the semaphore and budget state (tests and configuration reloads)."""
        self._run_times.clear()
        self._in_use = 0
        self._semaphore = None
        self._loop = None
        set_analysis_in_flight(0)


_gate: AnalysisGate | None = None
_gate_config: tuple[int, float, int, float] | None = None

_store: AnalysisStateStore | None = None
_store_config: int | None = None


def get_analysis_gate() -> AnalysisGate:
    """Return the process-wide gate, rebuilding it if settings changed."""
    global _gate, _gate_config  # noqa: PLW0603
    from configs.settings import settings

    config = (
        settings.analysis_max_concurrent,
        settings.analysis_timeout_seconds,
        settings.analysis_max_runs_per_hour,
        settings.analysis_queue_timeout_seconds,
    )
    if _gate is None or _gate_config != config:
        _gate = AnalysisGate(*config)
        _gate_config = config
    return _gate


def get_analysis_state_store() -> AnalysisStateStore:
    """Return the process-wide per-session state store."""
    global _store, _store_config  # noqa: PLW0603
    from configs.settings import settings

    if _store is None or _store_config != settings.analysis_state_cache_size:
        _store = AnalysisStateStore(settings.analysis_state_cache_size)
        _store_config = settings.analysis_state_cache_size
    return _store


def reset_analysis_control() -> None:
    """Reset the gate and state store (tests and configuration reloads)."""
    global _gate, _gate_config, _store, _store_config  # noqa: PLW0603
    if _gate is not None:
        _gate.reset()
    _gate = None
    _gate_config = None
    _store = None
    _store_config = None
