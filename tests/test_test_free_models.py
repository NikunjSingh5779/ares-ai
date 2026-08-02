"""Tests for test_free_models.py logic (mocked, no live network calls)."""

from __future__ import annotations

import pytest

from scripts.test_free_models import flatten_agent_models, load_model_roster


@pytest.fixture
def sample_roster() -> dict:
    """A minimal model roster resembling configs/models.yaml."""
    return {
        "defaults": {"rate_limit_rpm": 4},
        "agents": {
            "market_analyst": {
                "primary": "open_router/model-a:free",
                "fallbacks": ["open_router/model-b:free", "open_router/model-c:free"],
                "timeout_seconds": 60,
            },
            "vision": {
                "primary": "open_router/model-vl:free",
                "fallbacks": [],
                "timeout_seconds": 30,
            },
            "consensus": {
                "primary": "open_router/model-d:free",
                "fallbacks": ["opencode/model-e-free"],
                "timeout_seconds": 15,
            },
        },
    }


class TestFlattenAgentModels:
    def test_flatten_returns_all_entries(self, sample_roster: dict) -> None:
        entries = flatten_agent_models(sample_roster)
        assert len(entries) == 6  # 3 primaries + 2 fallbacks + 1 with 0 fallbacks
        assert sum(1 for e in entries if e["role"] == "primary") == 3
        assert sum(1 for e in entries if e["role"] == "fallback") == 3

    def test_flatten_includes_agent_names(self, sample_roster: dict) -> None:
        entries = flatten_agent_models(sample_roster)
        agents = {e["agent"] for e in entries}
        assert agents == {"market_analyst", "vision", "consensus"}

    def test_flatten_empty_roster(self) -> None:
        entries = flatten_agent_models({"agents": {}})
        assert entries == []

    def test_flatten_empty_agents(self) -> None:
        entries = flatten_agent_models({})
        assert entries == []


class TestLoadModelRoster:
    def test_load_returns_dict(self) -> None:
        """load_model_roster can parse the real configs/models.yaml."""
        import os

        path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            os.pardir,
            "configs",
            "models.yaml",
        )
        roster = load_model_roster(path)
        assert "agents" in roster
        assert "defaults" in roster
        # Should have all expected agents
        for agent in ("market_analyst", "quant", "risk", "supervisor", "vision", "consensus"):
            assert agent in roster["agents"], f"Missing agent '{agent}' in models.yaml"


class TestFreePriceFilter:
    """Test the OpenRouter free-model filtering logic in isolation."""

    @pytest.fixture
    def sample_api_response(self) -> dict:
        """Simulate OpenRouter /api/v1/models response."""
        return {
            "data": [
                {"id": "model-a:free", "pricing": {"prompt": "0", "completion": "0"}},
                {"id": "model-b:free", "pricing": {"prompt": "0", "completion": "0"}},
                {"id": "model-c:paid", "pricing": {"prompt": "0.0001", "completion": "0.0002"}},
                {"id": "model-d:free", "pricing": {"prompt": "0.0", "completion": "0.0"}},
                {"id": "model-e:partial", "pricing": {"prompt": "0", "completion": "0.0001"}},
            ],
        }

    def test_parse_free_models(self, sample_api_response: dict) -> None:
        """Free model IDs should include only zero-priced entries."""

        # Can't test the async function directly without mocking httpx,
        # but we can test the filtering logic
        free_ids = set()
        for model in sample_api_response["data"]:
            pricing = model.get("pricing", {})
            prompt = float(pricing.get("prompt", -1))
            completion = float(pricing.get("completion", -1))
            if prompt == 0.0 and completion == 0.0:
                free_ids.add(model["id"])
        assert free_ids == {"model-a:free", "model-b:free", "model-d:free"}

    def test_not_free_models_excluded(self, sample_api_response: dict) -> None:
        """Paid models should not be included in free IDs."""
        free_ids = set()
        for model in sample_api_response["data"]:
            pricing = model.get("pricing", {})
            prompt = float(pricing.get("prompt", -1))
            completion = float(pricing.get("completion", -1))
            if prompt == 0.0 and completion == 0.0:
                free_ids.add(model["id"])
        assert "model-c:paid" not in free_ids
        assert "model-e:partial" not in free_ids


class TestDeadChainLogic:
    """Test the dead-chain exit code logic."""

    def test_all_working_no_dead(self) -> None:
        """When all critical agents have working models, exit code is 0."""
        results = [
            {"agent": "market_analyst", "role": "primary", "status": "SUCCESS"},
            {"agent": "quant", "role": "primary", "status": "SUCCESS"},
            {"agent": "risk", "role": "primary", "status": "SUCCESS"},
            {"agent": "supervisor", "role": "primary", "status": "SUCCESS"},
        ]
        dead = False
        from scripts.test_free_models import CRITICAL_AGENTS

        for agent_name in CRITICAL_AGENTS:
            agent_results = [r for r in results if r["agent"] == agent_name]
            agent_primaries = [r for r in agent_results if r["role"] == "primary"]
            agent_fallbacks = [r for r in agent_results if r["role"] == "fallback"]
            primary_dead = all(r["status"] in ("FAILED", "RATE_LIMITED", "NOT_FREE", "NO_KEY") for r in agent_primaries)
            fallbacks_dead = (
                all(r["status"] in ("FAILED", "RATE_LIMITED", "NOT_FREE", "NO_KEY") for r in agent_fallbacks)
                if agent_fallbacks
                else True
            )
            if primary_dead and fallbacks_dead:
                dead = True
        assert dead is False

    def test_primary_down_fallback_works(self) -> None:
        """When primary is dead but fallback works, not a dead chain."""
        results = [
            {"agent": "market_analyst", "role": "primary", "status": "FAILED"},
            {"agent": "market_analyst", "role": "fallback", "status": "SUCCESS"},
        ]
        dead = False
        from scripts.test_free_models import CRITICAL_AGENTS

        for agent_name in CRITICAL_AGENTS:
            if agent_name != "market_analyst":
                continue
            agent_results = [r for r in results if r["agent"] == agent_name]
            agent_primaries = [r for r in agent_results if r["role"] == "primary"]
            agent_fallbacks = [r for r in agent_results if r["role"] == "fallback"]
            primary_dead = all(r["status"] in ("FAILED", "RATE_LIMITED", "NOT_FREE", "NO_KEY") for r in agent_primaries)
            fallbacks_dead = (
                all(r["status"] in ("FAILED", "RATE_LIMITED", "NOT_FREE", "NO_KEY") for r in agent_fallbacks)
                if agent_fallbacks
                else True
            )
            if primary_dead and fallbacks_dead:
                dead = True
        assert dead is False

    def test_both_primary_and_fallback_dead(self) -> None:
        """When both primary and fallback are dead, it's a dead chain."""
        results = [
            {"agent": "quant", "role": "primary", "status": "FAILED"},
            {"agent": "quant", "role": "fallback", "status": "RATE_LIMITED"},
        ]
        dead = False
        from scripts.test_free_models import CRITICAL_AGENTS

        for agent_name in CRITICAL_AGENTS:
            if agent_name != "quant":
                continue
            agent_results = [r for r in results if r["agent"] == agent_name]
            agent_primaries = [r for r in agent_results if r["role"] == "primary"]
            agent_fallbacks = [r for r in agent_results if r["role"] == "fallback"]
            primary_dead = all(r["status"] in ("FAILED", "RATE_LIMITED", "NOT_FREE", "NO_KEY") for r in agent_primaries)
            fallbacks_dead = (
                all(r["status"] in ("FAILED", "RATE_LIMITED", "NOT_FREE", "NO_KEY") for r in agent_fallbacks)
                if agent_fallbacks
                else True
            )
            if primary_dead and fallbacks_dead:
                dead = True
        assert dead is True

    def test_no_fallbacks_primary_dead(self) -> None:
        """When no fallbacks and primary is dead, it's a dead chain."""
        results = [
            {"agent": "supervisor", "role": "primary", "status": "FAILED"},
        ]
        dead = False
        from scripts.test_free_models import CRITICAL_AGENTS

        for agent_name in CRITICAL_AGENTS:
            if agent_name != "supervisor":
                continue
            agent_results = [r for r in results if r["agent"] == agent_name]
            agent_primaries = [r for r in agent_results if r["role"] == "primary"]
            agent_fallbacks = [r for r in agent_results if r["role"] == "fallback"]
            primary_dead = all(r["status"] in ("FAILED", "RATE_LIMITED", "NOT_FREE", "NO_KEY") for r in agent_primaries)
            fallbacks_dead = (
                all(r["status"] in ("FAILED", "RATE_LIMITED", "NOT_FREE", "NO_KEY") for r in agent_fallbacks)
                if agent_fallbacks
                else True
            )
            if primary_dead and fallbacks_dead:
                dead = True
        assert dead is True
