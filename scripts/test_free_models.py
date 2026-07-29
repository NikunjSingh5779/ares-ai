#!/usr/bin/env python
"""Free-tier model health checker for ARES AI.

Tests every primary and fallback model ID for every agent in
configs/models.yaml.  Reports SUCCESS / RATE_LIMITED / FAILED /
NOT_FREE / NO_KEY for each.

Usage:
    uv run python scripts/test_free_models.py                  # full check
    uv run python scripts/test_free_models.py --dry-run        # list only
    uv run python scripts/test_free_models.py --agent vision   # one agent
    uv run python scripts/test_free_models.py --quiet-warn-only  # pre-flight
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any

import httpx
import yaml

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.client import LLMClient

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CRITICAL_AGENTS = {"market_analyst", "quant", "risk", "supervisor"}
"""Agents whose primary model being dead counts as a CI-blocking failure."""

PROBE_MESSAGE: list[dict[str, str]] = [
    {"role": "user", "content": "Reply with OK only."},
]
PROBE_MAX_TOKENS = 16
PROBE_TIMEOUT = 30


# ---------------------------------------------------------------------------
# Model roster loader
# ---------------------------------------------------------------------------


def load_model_roster(path: str | None = None) -> dict[str, Any]:
    """Load model roster from configs/models.yaml.

    Returns::
        {
          "agents": {
            "market_analyst": {
              "primary": "open_router/...",
              "fallbacks": [...],
              "timeout_seconds": 60,
              ...
            },
            ...
          },
          "defaults": { "rate_limit_rpm": 4, ... },
        }
    """
    if path is None:
        path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "configs", "models.yaml")
    with open(path) as f:
        data: dict[str, Any] = yaml.safe_load(f)
    return data


def flatten_agent_models(roster: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten the roster into a list of (agent, role, model_id) entries."""
    entries: list[dict[str, Any]] = []
    agents = roster.get("agents", {})
    for agent_name, cfg in agents.items():
        primary = cfg.get("primary")
        if primary:
            entries.append({"agent": agent_name, "role": "primary", "model": primary})
        for fb in cfg.get("fallbacks", []):
            entries.append({"agent": agent_name, "role": "fallback", "model": fb})
    return entries


# ---------------------------------------------------------------------------
# OpenRouter free-model list fetcher
# ---------------------------------------------------------------------------


async def fetch_free_model_ids() -> set[str]:
    """Fetch the live set of free (zero-cost) model IDs from OpenRouter."""
    async with httpx.AsyncClient() as client:
        resp = await client.get("https://openrouter.ai/api/v1/models", timeout=15)
        resp.raise_for_status()
        data = resp.json()
    free: set[str] = set()
    for model in data.get("data", []):
        pricing = model.get("pricing", {})
        try:
            prompt = float(pricing.get("prompt", -1))
            completion = float(pricing.get("completion", -1))
        except (TypeError, ValueError):
            continue
        if prompt == 0.0 and completion == 0.0:
            free.add(model["id"])
    return free


# ---------------------------------------------------------------------------
# Per-model probe
# ---------------------------------------------------------------------------


async def probe_model(
    client: LLMClient,
    model_id: str,
    timeout_s: int = PROBE_TIMEOUT,
) -> dict[str, Any]:
    """Probe a single model via LLMClient.chat_completion.

    Returns a status dict with ``status`` in
    {SUCCESS, RATE_LIMITED, FAILED, NO_KEY}.
    """
    try:
        resp = await client.chat_completion(
            model=model_id,
            messages=PROBE_MESSAGE,
            max_tokens=PROBE_MAX_TOKENS,
            timeout=timeout_s,
        )
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 429:
            return {"status": "RATE_LIMITED", "detail": str(e)}
        return {"status": "FAILED", "detail": str(e)}
    except Exception as e:
        return {"status": "FAILED", "detail": f"{type(e).__name__}: {e}"}

    # Check error envelope from LLMClient
    if resp.get("error"):
        err_type = resp.get("error_type", "")
        status_code = resp.get("status_code")
        if status_code == 429 or "rate" in str(resp.get("choices", [{}])).lower():
            return {"status": "RATE_LIMITED", "detail": resp.get("error", "")}
        if err_type == "NoOpClient" or "no API key" in str(resp.get("choices", [{}])).lower():
            return {"status": "NO_KEY", "detail": "Provider API key not configured"}
        return {"status": "FAILED", "detail": resp.get("error", str(resp))}

    return {"status": "SUCCESS", "detail": None}


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def print_results_table(
    results: list[dict[str, Any]],
    free_ids: set[str] | None,
) -> None:
    """Print a formatted results table."""
    header = f"{'Agent':<20} {'Role':<10} {'Status':<15} {'Model':<55}"
    sep = "-" * len(header)
    print(f"\n{'Model Health Check Results':^100}")
    print(sep)
    print(header)
    print(sep)

    for r in results:
        agent = r["agent"]
        role = r["role"]
        model = r["model"]
        status = r["status"]

        # Check if model is on the free list
        if free_ids is not None and status in ("SUCCESS", "FAILED"):
            or_id = model.replace("open_router/", "", 1)
            if or_id not in free_ids and "open_router" in model:
                status = "NOT_FREE"

        print(f"{agent:<20} {role:<10} {status:<15} {model:<55}")

    print(sep)

    # Summary counts
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
    print(f"Summary: {summary}")


def print_dead_chain_yaml(results: list[dict[str, Any]]) -> None:
    """Print a ready-to-paste YAML snippet for agents whose entire chain is dead."""
    # Group by agent
    by_agent: dict[str, list[dict[str, Any]]] = {}
    for r in results:
        by_agent.setdefault(r["agent"], []).append(r)

    dead_chains = []
    for agent, entries in sorted(by_agent.items()):
        all_dead = all(e["status"] in ("FAILED", "RATE_LIMITED", "NOT_FREE", "NO_KEY") for e in entries)
        if all_dead:
            dead_chains.append(agent)
            print(f"\n[!] Agent '{agent}' has NO working models:")
            for e in entries:
                print(f"    {e['role']}: {e['model']} → {e['status']}")

    if dead_chains:
        print(
            "\nReady-to-paste YAML (replacement config section):\n"
            "# TODO: Replace these models with working free models\n"
        )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> int:  # noqa: PLR0915
    """Run the model health check.  Returns exit code (0 = ok, 1 = dead chain)."""
    parser = argparse.ArgumentParser(description="Free-tier model health checker")
    parser.add_argument("--dry-run", action="store_true", help="List models without probing")
    parser.add_argument("--agent", type=str, default=None, help="Test only one agent's chain")
    parser.add_argument("--quiet-warn-only", action="store_true", help="Never block, only warn")
    args = parser.parse_args()

    # Load config
    roster = load_model_roster()
    defaults = roster.get("defaults", {})
    rpm = defaults.get("rate_limit_rpm", 4)
    delay_between = 60.0 / rpm  # seconds between probes

    # Build the list of models to test
    all_entries = flatten_agent_models(roster)
    if args.agent:
        all_entries = [e for e in all_entries if e["agent"] == args.agent]
        if not all_entries:
            print(f"No models found for agent '{args.agent}'")
            return 1

    print(f"Loaded {len(all_entries)} model entries from configs/models.yaml")

    # Fetch OpenRouter free model list
    free_ids: set[str] | None = None
    if not args.dry_run:
        try:
            free_ids = await fetch_free_model_ids()
            print(f"OpenRouter reports {len(free_ids)} free models")
        except Exception as e:
            print(f"Warning: could not fetch OpenRouter free list: {e}")

    # Dry run — list only
    if args.dry_run:
        print(f"\n{'Agent':<20} {'Role':<10} {'Model':<55}")
        print("-" * 85)
        for e in all_entries:
            print(f"{e['agent']:<20} {e['role']:<10} {e['model']:<55}")
        return 0

    # Create single LLMClient (auto-populates all provider credentials from env)
    client = LLMClient()
    print("LLMClient initialised (providers: {})".format(", ".join(client.providers.keys()) or "none"))

    # Probe each model
    results: list[dict[str, Any]] = []
    for i, entry in enumerate(all_entries):
        model_id = entry["model"]
        agent_name = entry["agent"]
        role = entry["role"]

        # Check API key availability
        provider = model_id.split("/")[0] if "/" in model_id else "default"
        provider_key = None
        # LLMClient stores providers as dict
        if provider in client.providers:
            provider_key = client.providers[provider].get("api_key") or client.providers[provider].get("api_key", "")
        if not provider_key or not client._is_valid_key(provider_key):
            results.append({
                "agent": agent_name,
                "role": role,
                "model": model_id,
                "status": "NO_KEY",
            })
            continue

        # Check if the model is on OpenRouter's free list before probing
        if free_ids is not None and "open_router" in provider:
            or_id = model_id.replace("open_router/", "", 1) if model_id.startswith("open_router/") else model_id
            if or_id not in free_ids:
                results.append({
                    "agent": agent_name,
                    "role": role,
                    "model": model_id,
                    "status": "NOT_FREE",
                })
                continue

        # Probe
        sys.stdout.write(f"[{i + 1}/{len(all_entries)}] Testing {model_id:<55} ... ")
        sys.stdout.flush()

        status = await probe_model(client, model_id)
        results.append({
            "agent": agent_name,
            "role": role,
            "model": model_id,
            "status": status["status"],
        })

        print(status["status"])
        sys.stdout.flush()

        if i < len(all_entries) - 1:
            await asyncio.sleep(delay_between)

    # Print results
    print_results_table(results, free_ids)
    print_dead_chain_yaml(results)

    # Determine exit code
    dead_critical = False
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
            dead_critical = True

    if dead_critical:
        message = "CRITICAL: One or more critical agents have no working models."
        if args.quiet_warn_only:
            print(f"\n[WARN] {message}")
            return 0
        print(f"\n[FAIL] {message}")
        return 1

    print("\nAll critical agents have at least one working model.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
