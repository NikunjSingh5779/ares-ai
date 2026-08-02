"""OpenRouter model-catalog validation for the free-only runtime.

A :class:`ModelCatalogValidator` queries the OpenRouter ``/api/v1/models``
endpoint and decides which configured models are *eligible* for the free-only
paper-trading runtime. A model is eligible only if ALL of the following hold:

* it exists in the live OpenRouter catalog;
* it advertises a zero prompt price AND a zero completion price;
* it supports the required structured (JSON Schema) output.

Successful validations are cached in memory for 24 hours so the healthy
runtime does not re-fetch the catalog on every request.

Guarantees (enforced here, not advisory):

* **Fail closed** — a missing / paid / incompatible model disqualifies the
  whole chain; the agent is treated as unavailable (no trade) and the model is
  never invoked.
* **No automatic replacement** — a disqualified model is never silently
  swapped for an arbitrary stand-in.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TTL_SECONDS: int = 24 * 60 * 60  # 24 hours

# OpenRouter entries advertise structured output via these supported_parameters.
_STRUCTURED_PARAMS = ("response_format", "json_schema")


def _strip_prefix(model_id: str) -> str:
    """Normalise ``open_router/org/model:free`` -> ``org/model:free``."""
    prefix = "open_router/"
    return model_id[len(prefix) :] if model_id.startswith(prefix) else model_id


def _is_zero_price(value: Any) -> bool:
    try:
        return float(value) == 0.0
    except (TypeError, ValueError):
        return False


@dataclass
class ModelStatus:
    """Result of validating a single model against the catalog."""

    model: str
    eligible: bool = False
    reasons: list[str] = field(default_factory=list)
    exists: bool = False
    zero_price: bool = False
    supports_structured_output: bool = False


class ModelCatalogValidator:
    """Validates configured models against the live OpenRouter catalog.

    Args:
        base_url: OpenRouter base URL (``/models`` is appended).
        api_key: ``OPENROUTER_API_KEY`` — passed as Bearer auth when set; the
            validator itself never serializes or echoes this value.
        timeout_seconds: per-request timeout for the catalog fetch.
        cache_ttl_seconds: how long a successful fetch is reused (default 24h).
        require_structured_output: when True (default) a model without
            advertised structured-output support is excluded.
        accept_unknown_structured_output: when True a catalog entry that omits
            the structured-output capability flag is treated as capable.
            Default (False) FAILS CLOSED on unknown capability.
    """

    def __init__(
        self,
        base_url: str = "https://openrouter.ai/api/v1",
        api_key: str = "",
        timeout_seconds: float = 10.0,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        require_structured_output: bool = True,
        accept_unknown_structured_output: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.cache_ttl_seconds = cache_ttl_seconds
        self.require_structured_output = require_structured_output
        self.accept_unknown_structured_output = accept_unknown_structured_output

        self._catalog: dict[str, dict[str, Any]] = {}
        self._catalog_fetched_at: float = 0.0
        self._cache_valid: bool = False
        self._last_error: str | None = None
        self._client: httpx.AsyncClient | None = None

    # ── Cache state (read by the health endpoint) ──────────────────────────

    @property
    def is_cached(self) -> bool:
        return self._cache_valid

    @property
    def cache_age_seconds(self) -> float:
        if not self._cache_valid or self._catalog_fetched_at == 0.0:
            return -1.0
        return max(0.0, time.monotonic() - self._catalog_fetched_at)

    @property
    def last_error(self) -> str | None:
        return self._last_error

    # ── Transport ──────────────────────────────────────────────────────────

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            headers = {"Content-Type": "application/json", "Accept": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=headers,
                timeout=self.timeout_seconds,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
        self._client = None

    # ── Catalog fetch + cache ──────────────────────────────────────────────

    async def fetch_models(self) -> dict[str, dict[str, Any]]:
        """Fetch ``/api/v1/models`` and return ``{id -> entry}``.

        On network/HTTP failure the previous cached catalog (if any) is kept so
        a transient blip does not wipe a validated free-only snapshot. If there
        is nothing cached and the fetch fails, the catalog is empty and every
        chain fails closed.
        """
        client = self._get_client()
        try:
            resp = await client.get("/models")
            resp.raise_for_status()
            payload = resp.json()
            data = payload.get("data", []) if isinstance(payload, dict) else payload
            catalog: dict[str, dict[str, Any]] = {}
            for entry in data or []:
                model_id = entry.get("id")
                if model_id:
                    catalog[model_id] = entry
            # A successful fresh fetch replaces the snapshot.
            self._catalog = catalog
            self._cache_valid = True
            self._catalog_fetched_at = time.monotonic()
            self._last_error = None
            logger.info("Fetched free-only OpenRouter catalog (%d models)", len(catalog))
        except Exception as exc:  # noqa: BLE001 - fail closed on any transport error
            self._last_error = f"{type(exc).__name__}: {exc}"
            logger.error("Catalog fetch failed: %s", self._last_error)
            if not self._cache_valid:
                self._catalog = {}
                self._cache_valid = True  # empty snapshot == fail-closed baseline
                self._catalog_fetched_at = time.monotonic()
        return dict(self._catalog)

    def _cache_is_fresh(self) -> bool:
        if not self._cache_valid:
            return False
        if self.cache_ttl_seconds <= 0:
            return True
        return self.cache_age_seconds <= self.cache_ttl_seconds

    async def ensure_catalog(self) -> None:
        """Fetch the catalog unless a fresh validated snapshot is cached."""
        if not self._cache_is_fresh():
            await self.fetch_models()

    def clear_cache(self) -> None:
        """Force the next validation to re-fetch the catalog."""
        self._cache_valid = False
        self._catalog = {}
        self._catalog_fetched_at = 0.0

    # ── Eligibility ────────────────────────────────────────────────────────

    def _supports_structured_output(self, entry: dict[str, Any]) -> bool:
        supported = entry.get("supported_parameters")
        if isinstance(supported, list):
            return bool(set(_STRUCTURED_PARAMS).intersection(supported))
        # Capability flag absent — fail closed unless explicitly opted out.
        return self.accept_unknown_structured_output

    def _status(self, model_id: str, entry: dict[str, Any]) -> ModelStatus:
        pricing = entry.get("pricing", {}) if isinstance(entry, dict) else {}
        prompt = pricing.get("prompt")
        completion = pricing.get("completion")
        zero_price = _is_zero_price(prompt) and _is_zero_price(completion)
        supports = self._supports_structured_output(entry)

        reasons: list[str] = []
        if not zero_price:
            reasons.append(f"non-zero price (prompt={prompt!r}, completion={completion!r})")
        if self.require_structured_output and not supports:
            reasons.append("does not advertise structured (JSON Schema) output")

        return ModelStatus(
            model=model_id,
            eligible=zero_price and (not self.require_structured_output or supports),
            reasons=reasons,
            exists=True,
            zero_price=zero_price,
            supports_structured_output=supports,
        )

    async def validate_model(self, model_id: str) -> ModelStatus:
        """Validate one model id against the live (cached) catalog."""
        await self.ensure_catalog()
        resolved = _strip_prefix(model_id)
        entry = self._catalog.get(resolved)
        if entry is None:
            return ModelStatus(model=model_id, eligible=False, reasons=["model not present in OpenRouter catalog"])
        return self._status(model_id, entry)

    async def validate_chain(self, chain: list[str]) -> tuple[bool, list[ModelStatus]]:
        """Validate an ordered model chain.

        Returns ``(all_eligible, statuses)``. The chain is eligible only if
        EVERY model is eligible — a single missing/paid/incompatible model
        disables the whole chain (fail closed).
        """
        statuses = [await self.validate_model(model) for model in chain]
        all_eligible = bool(statuses) and all(status.eligible for status in statuses)
        return all_eligible, statuses

    async def roster_report(
        self,
        roster,
        agent_names: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Build a redacted eligibility report for an array of agents.

        Only model ids and reasons are surfaced — never the API key or request
        content — so this is safe to expose via ``/model-health``.
        """
        await self.ensure_catalog()
        names = roster.agent_names if agent_names is None else list(agent_names)
        report: dict[str, Any] = {}
        for name in names:
            try:
                cfg = roster.get(name)
            except KeyError:
                report[name] = {"eligible": False, "models": [], "reasons": ["no model config"]}
                continue
            chain = cfg.model_chain
            if not chain:
                report[name] = {"eligible": True, "models": [], "reasons": ["deterministic (no LLM)"]}
                continue
            all_eligible, statuses = await self.validate_chain(chain)
            report[name] = {
                "eligible": all_eligible,
                "models": [status.model for status in statuses],
                "reasons": [
                    f"{status.model}: {'ok' if status.eligible else ' | '.join(status.reasons) or 'ineligible'}"
                    for status in statuses
                ],
            }
        return report


def default_catalog() -> ModelCatalogValidator:
    """Build a catalog validator bound to the current settings.

    Test-safe: no real key is used unless ``OPENROUTER_API_KEY`` is present in
    the environment / settings, and the endpoint is never hit on import.
    """
    from backend.core.config import settings

    return ModelCatalogValidator(
        base_url=settings.openrouter_base_url,
        api_key=settings.openrouter_api_key,
        require_structured_output=True,
    )
