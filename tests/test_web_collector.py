"""Free-only policy tests for the optional web collector agent."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import pytest

from agents.client import free_model_policy_violation
from agents.models import load_model_roster
from agents.web_collector import WebCollectorAgent, WebCollectorInput, _browser_llm_config
from configs.settings import settings

SOURCE_PATH = Path(__file__).resolve().parents[1] / "agents" / "web_collector.py"


class _FakeChatOpenRouter:
    """Records constructor kwargs instead of calling a provider."""

    calls: list[dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs
        _FakeChatOpenRouter.calls.append(kwargs)


class _FakeBrowserAgent:
    """Minimal browser-use Agent stand-in."""

    def __init__(self, **kwargs: Any) -> None:
        self.kwargs = kwargs

    async def run(self, max_steps: int) -> None:
        return None


@pytest.fixture
def fake_browser_modules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install fake optional dependencies so the browser path is reachable."""
    _FakeChatOpenRouter.calls = []

    browser_use = types.ModuleType("browser_use")
    browser_use.Agent = _FakeBrowserAgent  # type: ignore[attr-defined]
    browser_use.ChatOpenRouter = _FakeChatOpenRouter  # type: ignore[attr-defined]

    monkeypatch.setitem(sys.modules, "browser_use", browser_use)


class TestWebCollectorFreeOnlyPolicy:
    def test_source_has_no_hardcoded_paid_models(self) -> None:
        source = SOURCE_PATH.read_text(encoding="utf-8")
        assert "gpt-4o" not in source
        assert "gemini-2.0" not in source
        assert "openai/" not in source
        assert "gemini/" not in source
        assert "gemini_api_key" not in source

    def test_roster_entry_is_free(self) -> None:
        config = load_model_roster().get("web_collector")
        assert config.model_chain
        for model_id in config.model_chain:
            assert free_model_policy_violation(model_id) is None, model_id

    @pytest.mark.parametrize(
        "model",
        [
            "open_router/openai/gpt-4o",
            "open_router/google/gemini-2.0-flash",
            "google/gemini-2.0-flash",
            "mistral/mistral-large",
            "opencode/gpt-4o",
        ],
    )
    def test_policy_rejects_paid_models(self, model: str) -> None:
        assert free_model_policy_violation(model) is not None

    @pytest.mark.parametrize(
        "model",
        [
            "open_router/openrouter/free",
            "openrouter/free",
            "open_router/google/gemma-4-26b-a4b-it:free",
            "local/qwen3.6-35b-a3b-ud-q4_k_m",
        ],
    )
    def test_policy_allows_free_and_local_models(self, model: str) -> None:
        assert free_model_policy_violation(model) is None

    def test_browser_model_comes_from_the_roster(self) -> None:
        assert _browser_llm_config().primary == "open_router/openrouter/free"

    def test_browser_model_rejects_a_paid_roster_entry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Roster:
            @staticmethod
            def get(name: str) -> Any:
                return types.SimpleNamespace(primary="open_router/openai/gpt-4o")

        monkeypatch.setattr("agents.web_collector.load_model_roster", lambda: _Roster())

        with pytest.raises(ValueError, match="free-only policy"):
            _browser_llm_config()

    def test_missing_roster_entry_raises_value_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Roster:
            @staticmethod
            def get(name: str) -> Any:
                raise KeyError(name)

        monkeypatch.setattr("agents.web_collector.load_model_roster", lambda: _Roster())

        with pytest.raises(ValueError, match="missing"):
            _browser_llm_config()


class TestWebCollectorBrowserPath:
    async def test_builds_the_free_roster_model(
        self, monkeypatch: pytest.MonkeyPatch, fake_browser_modules: None
    ) -> None:
        monkeypatch.setattr(settings, "openrouter_api_key", "test-key")

        result = await WebCollectorAgent()._collect_with_browser_use(WebCollectorInput(task="read a page"))

        assert result is not None
        assert result["success"] is True
        assert result["model_used"] == "browser-use"
        assert len(_FakeChatOpenRouter.calls) == 1
        kwargs = _FakeChatOpenRouter.calls[0]
        assert kwargs["model"] == "openrouter/free"
        assert kwargs["api_key"] == "test-key"
        assert kwargs["base_url"] == settings.openrouter_base_url
        assert kwargs["timeout"] == 60
        assert kwargs["extra_body"]["provider"]["max_price"] == {
            "prompt": 0,
            "completion": 0,
            "request": 0,
            "image": 0,
        }

    async def test_missing_openrouter_key_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch, fake_browser_modules: None
    ) -> None:
        monkeypatch.setattr(settings, "openrouter_api_key", "")

        result = await WebCollectorAgent()._collect_with_browser_use(WebCollectorInput(task="read a page"))

        assert result is not None
        assert result["success"] is False
        assert "OPENROUTER_API_KEY" in result["error"]
        assert _FakeChatOpenRouter.calls == []

    async def test_paid_roster_entry_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch, fake_browser_modules: None
    ) -> None:
        class _Roster:
            @staticmethod
            def get(name: str) -> Any:
                return types.SimpleNamespace(primary="open_router/openai/gpt-4o")

        monkeypatch.setattr(settings, "openrouter_api_key", "test-key")
        monkeypatch.setattr("agents.web_collector.load_model_roster", lambda: _Roster())

        result = await WebCollectorAgent()._collect_with_browser_use(WebCollectorInput(task="read a page"))

        assert result is not None
        assert result["success"] is False
        assert "free-only policy" in result["error"]
        assert _FakeChatOpenRouter.calls == []

    async def test_missing_optional_dependency_degrades(
        self, monkeypatch: pytest.MonkeyPatch, fake_browser_modules: None
    ) -> None:
        # Replace the fake module with None: importing it raises ImportError.
        monkeypatch.setitem(sys.modules, "browser_use", None)

        result = await WebCollectorAgent().process(WebCollectorInput(task="read a page"))

        assert result["success"] is False
        assert "browser-use not available" in result["error"]
