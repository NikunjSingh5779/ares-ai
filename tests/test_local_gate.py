"""Tests for the process-wide local-model concurrency gate."""

from __future__ import annotations

import asyncio

import pytest

from agents.local_gate import (
    LocalModelBusyError,
    LocalModelGate,
    get_local_model_gate,
    reset_local_model_gate,
)


async def test_gate_serializes_local_requests() -> None:
    gate = LocalModelGate(max_concurrent=1, queue_timeout_seconds=1.0)
    events: list[str] = []

    async def worker(name: str, hold_seconds: float) -> None:
        await gate.acquire()
        try:
            events.append(f"{name}:start")
            await asyncio.sleep(hold_seconds)
            events.append(f"{name}:end")
        finally:
            gate.release()

    await asyncio.gather(worker("a", 0.05), worker("b", 0.01))

    assert events == ["a:start", "a:end", "b:start", "b:end"]
    assert gate.in_use == 0


async def test_gate_fails_closed_when_full() -> None:
    gate = LocalModelGate(max_concurrent=1, queue_timeout_seconds=0.01)
    await gate.acquire()
    try:
        with pytest.raises(LocalModelBusyError, match="busy"):
            await gate.acquire()
    finally:
        gate.release()


async def test_gate_allows_configured_parallelism() -> None:
    gate = LocalModelGate(max_concurrent=2, queue_timeout_seconds=1.0)
    release = asyncio.Event()

    async def worker() -> None:
        await gate.acquire()
        try:
            await release.wait()
        finally:
            gate.release()

    tasks = [asyncio.create_task(worker()) for _ in range(2)]
    try:
        while gate.in_use < 2:
            await asyncio.sleep(0.01)
        assert gate.in_use == 2
    finally:
        release.set()
        await asyncio.gather(*tasks)


def test_gate_singleton_is_process_wide_and_resettable() -> None:
    reset_local_model_gate()
    try:
        first = get_local_model_gate()
        assert get_local_model_gate() is first
        reset_local_model_gate()
        assert get_local_model_gate() is not first
    finally:
        reset_local_model_gate()
