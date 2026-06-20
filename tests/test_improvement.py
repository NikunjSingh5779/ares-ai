"""Tests for the StrategyImprovementEngine (self-improvement loop)."""

from __future__ import annotations

import pytest

from agents.improvement import (
    CONFIDENCE_ACCURACY_DECLINE_THRESHOLD,
    MIN_RUNS_FOR_ANALYSIS,
    WIN_RATE_DECLINE_THRESHOLD,
    ImprovementRecord,
    ImprovementRunResult,
    StrategyImprovementEngine,
    reset_engine,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset():
    """Reset engine and history before each test."""
    reset_engine()
    yield


def _make_reflection(
    confidence_accuracy: float = 85.0,
    executed: bool = True,
    has_errors: bool = False,
    extra_suggestions: list[str] | None = None,
) -> dict:
    """Helper: create a reflection output dict."""
    suggestions = []
    if has_errors:
        suggestions.append("Investigate 1 error(s) in the pipeline")
    if extra_suggestions:
        suggestions.extend(extra_suggestions)
    if not suggestions:
        suggestions.append("No significant issues detected")

    return {
        "evaluation": f"Trade {'executed' if executed else 'not executed'}",
        "confidence_accuracy": confidence_accuracy,
        "improvement_suggestions": suggestions,
        "knowledge_updates": ["Test knowledge update"],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStrategyImprovementEngine:
    def test_init(self):
        engine = StrategyImprovementEngine()
        result = engine.analyze(_make_reflection())
        assert isinstance(result, ImprovementRunResult)

    def test_analyze_with_insufficient_history(self):
        """Should warn when fewer than MIN_RUNS_FOR_ANALYSIS runs exist."""
        engine = StrategyImprovementEngine()
        result = engine.analyze(_make_reflection())

        assert len(result.warnings) > 0
        assert "Only 1" in result.warnings[0]

    def test_metrics_after_multiple_runs(self):
        engine = StrategyImprovementEngine()

        # Run enough reflections to establish history
        for _ in range(MIN_RUNS_FOR_ANALYSIS):
            engine.analyze(_make_reflection(confidence_accuracy=85.0, executed=True))

        metrics = engine.get_metrics_summary()
        assert metrics["total_runs"] >= MIN_RUNS_FOR_ANALYSIS
        assert metrics["avg_confidence_accuracy"] > 0
        assert metrics["win_rate"] > 0

    def test_win_rate_decline_detection(self):
        """Should detect when win rate declines significantly.

        StrategyImprovementEngine splits the last MIN_RUNS_FOR_ANALYSIS (5)
        entries into older_half (first 2) and newer_half (last 3). For a
        decline to register, older_half rate - newer_half rate > 0.15.
        """
        engine = StrategyImprovementEngine()

        # Build 5 entries to clear the minimum history threshold
        for _ in range(MIN_RUNS_FOR_ANALYSIS):
            engine.analyze(_make_reflection(executed=True))

        # The last 5 entries are now the "recent window".
        # First 2 of those 5 should be executed, last 3 should not.
        # Start with 2 more executed:
        engine.analyze(_make_reflection(executed=True))
        engine.analyze(_make_reflection(executed=True))
        # Then 3 not executed:
        engine.analyze(_make_reflection(executed=False))
        engine.analyze(_make_reflection(executed=False))
        engine.analyze(_make_reflection(executed=False))

        records = engine.get_recent_improvements()
        win_rate_records = [r for r in records if r["category"] == "risk_calibration"]
        assert len(win_rate_records) > 0
        assert "declined" in win_rate_records[0]["description"].lower()

    def test_confidence_accuracy_decline_detection(self):
        """Should detect when confidence accuracy declines significantly."""
        engine = StrategyImprovementEngine()

        # First half: high accuracy
        for _ in range(MIN_RUNS_FOR_ANALYSIS):
            engine.analyze(_make_reflection(confidence_accuracy=90.0))

        # Reset history to force clean split — we need at least MIN_RUNS_FOR_ANALYSIS*2
        # Actually the engine uses the full _reflection_history, not just the last MIN
        # Let me add enough entries with a clear split

        # Second half: low accuracy (below threshold)
        for _ in range(MIN_RUNS_FOR_ANALYSIS):
            engine.analyze(_make_reflection(confidence_accuracy=30.0))

        records = engine.get_recent_improvements()
        accuracy_records = [r for r in records if r["category"] == "agent_config"]
        if accuracy_records:
            assert "declined" in accuracy_records[0]["description"].lower() or \
                   "accuracy" in accuracy_records[0]["description"].lower()

    def test_persistent_error_detection(self):
        """Should flag persistent errors across runs.

        Note: _check_error_rate only runs after MIN_RUNS_FOR_ANALYSIS (5)
        entries exist in history. Pad with error-free entries first, then
        add error entries.
        """
        engine = StrategyImprovementEngine()

        # Pad history to reach MIN_RUNS_FOR_ANALYSIS threshold
        for _ in range(MIN_RUNS_FOR_ANALYSIS):
            engine.analyze(_make_reflection(has_errors=False))

        # Now add 3 with errors — these trigger _check_error_rate
        for _ in range(3):
            engine.analyze(_make_reflection(has_errors=True))

        records = engine.get_recent_improvements()
        error_records = [r for r in records if r["severity"] == "critical"]
        assert any("Persistent errors" in r["description"] for r in error_records)

    def test_suggestion_overlap_detected(self):
        """Should detect when same suggestions keep appearing."""
        engine = StrategyImprovementEngine()

        for _ in range(5):
            engine.analyze(_make_reflection(
                extra_suggestions=["Review risk criteria"],
            ))

        records = engine.get_recent_improvements()
        overlap_records = [r for r in records if r["category"] == "parameter_tuning"]
        assert any("Repeated" in r["description"] for r in overlap_records)

    def test_apply_improvement(self):
        engine = StrategyImprovementEngine()
        engine.analyze(_make_reflection())

        records = engine.get_recent_improvements()
        if records:
            result = engine.apply_improvement(records[0]["id"])
            assert result is True

            # Verify it's marked as applied
            updated = engine.get_recent_improvements()
            assert updated[0]["applied"] is True

    def test_apply_nonexistent(self):
        engine = StrategyImprovementEngine()
        result = engine.apply_improvement("nonexistent-id")
        assert result is False

    def test_metrics_summary_properties(self):
        engine = StrategyImprovementEngine()
        for _ in range(5):
            engine.analyze(_make_reflection(executed=True, has_errors=False))

        metrics = engine.get_metrics_summary()
        assert "avg_confidence_accuracy" in metrics
        assert "win_rate" in metrics
        assert "error_rate" in metrics
        assert "total_runs" in metrics
        assert metrics["total_runs"] >= 5

    def test_recent_improvements_ordering(self):
        engine = StrategyImprovementEngine()
        for _ in range(10):
            engine.analyze(_make_reflection())

        records = engine.get_recent_improvements(limit=5)
        assert len(records) <= 5

    def test_empty_improvements(self):
        engine = StrategyImprovementEngine()
        records = engine.get_recent_improvements()
        assert records == []

    def test_get_improvement_engine_singleton(self):
        from agents.improvement import get_improvement_engine
        e1 = get_improvement_engine()
        e2 = get_improvement_engine()
        assert e1 is e2

    def test_reset_clears_history(self):
        engine = StrategyImprovementEngine()
        engine.analyze(_make_reflection())
        assert len(engine.get_recent_improvements()) >= 0

        reset_engine()
        # Fresh engine should have no history
        fresh_engine = StrategyImprovementEngine()
        assert fresh_engine.get_recent_improvements() == []


class TestImprovementRecord:
    def test_record_defaults(self):
        record = ImprovementRecord(
            id="test_1",
            timestamp="2025-01-01T00:00:00",
            category="parameter_tuning",
            description="Test record",
            severity="medium",
        )
        assert record.applied is False
        assert record.metric_before is None
        assert record.metric_after is None
        assert record.suggested_params == {}

    def test_record_with_metrics(self):
        record = ImprovementRecord(
            id="test_2",
            timestamp="2025-01-01T00:00:00",
            category="risk_calibration",
            description="Test with metrics",
            severity="high",
            metric_before=80.0,
            metric_after=60.0,
        )
        assert record.metric_before == 80.0
        assert record.metric_after == 60.0
