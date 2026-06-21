#!/usr/bin/env python
"""Full paper trading pipeline simulation.

Runs: analyze BTC-USD -> signal -> consensus -> risk -> execution -> audit
Uses mock/test data, no real API calls.
"""

import asyncio
import sys
import os
from typing import Any
from unittest.mock import AsyncMock

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agents.supervisor import Supervisor
from agents.registry import AgentRegistry
from agents.router import ModelRouter
from agents.log import AgentLogger
from agents.models import AgentModelConfig, ModelRoster
from agents.state import AgentState
from agents.circuit_breaker import CircuitBreakerRegistry
from agents.queue import QueueRegistry
from agents.retry import RetryConfig
from agents.client import NoOpLLMClient
from live_trading.audit import OrderAuditor, AuditEntry
from live_trading.safety import KillSwitch, ModeManager, PromotionGate, TradingMode
from live_trading.engine import LiveTradingEngine
from live_trading.exceptions import (
    ExchangeConnectionError,
    KillSwitchTrippedError,
    ModeError,
    PromotionGateError,
)
from live_trading.exchange.base import ExchangeConnector, ExchangeOrder


class MockExchangeConnector(ExchangeConnector):
    """Mock exchange connector for simulation - no real API calls."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        super().__init__("mock", config or {})
        self._connected = False

    async def connect(self) -> bool:
        self._connected = True
        return True

    async def disconnect(self) -> None:
        self._connected = False

    async def get_balance(self):
        from live_trading.exchange.base import ExchangeBalance
        return ExchangeBalance(
            total={"USDT": 100000.0, "BTC": 0.0},
            free={"USDT": 100000.0, "BTC": 0.0},
            used={"USDT": 0.0, "BTC": 0.0},
        )

    async def create_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        order_type: str,
        price: float | None = None,
        params: dict[str, Any] | None = None,
    ) -> ExchangeOrder:
        order_id = f"mock-order-{asyncio.get_event_loop().time():.0f}"
        return ExchangeOrder(
            id=order_id,
            symbol=symbol,
            side=side,
            type=order_type,
            quantity=quantity,
            price=price or 50000.0,
            filled=quantity,
            remaining=0.0,
            status="closed",
        )

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        return True

    async def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1d",
        limit: int = 100,
    ) -> list[list[float]]:
        """Return mock OHLCV candles."""
        # Return a small list of mock candles [timestamp, open, high, low, close, volume]
        now = int(asyncio.get_event_loop().time())
        candles = []
        base_price = 50000.0 if "BTC" in symbol else 3000.0
        for i in range(min(limit, 10)):
            timestamp = now - (9 - i) * 86400
            open_price = base_price + (i * 100)
            high = open_price + 200
            low = open_price - 100
            close = open_price + 50
            volume = 1000.0 + i * 100
            candles.append([timestamp, open_price, high, low, close, volume])
        return candles

    async def get_order_status(self, order_id: str, symbol: str) -> ExchangeOrder:
        """Return a mock order status matching create_order pattern."""
        return ExchangeOrder(
            id=order_id,
            symbol=symbol,
            side="buy",
            type="market",
            quantity=0.1,
            price=50000.0,
            filled=0.1,
            remaining=0.0,
            status="closed",
        )

    async def get_ticker(self, symbol: str) -> dict[str, Any]:
        """Return a mock ticker dict."""
        return {
            "symbol": symbol,
            "price": 50000.0,
            "bid": 49990.0,
            "ask": 50010.0,
            "volume": 100000.0,
            "high": 51000.0,
            "low": 49000.0,
            "change_pct": 2.5,
        }

    @property
    def is_connected(self) -> bool:
        return self._connected


async def main():
    print("=" * 60)
    print("ARES AI - Paper Trading Pipeline Simulation")
    print("=" * 60)

    # Setup components
    print("\n[1/6] Setting up components...")

    # Create model roster with all pipeline agents
    agent_configs = {}
    for name in ["market_analyst", "quant", "news", "vision", "consensus",
                  "risk", "execution", "journal", "reflection", "memory", "supervisor", "coding", "fast"]:
        agent_configs[name] = AgentModelConfig.from_dict(name, {"primary": f"model-{name}"})
    model_roster = ModelRoster(agent_configs)

    # Create dependencies
    breaker_registry = CircuitBreakerRegistry()
    queue_registry = QueueRegistry()
    retry_config = RetryConfig(max_retries=0, base_delay=0.01)
    llm_client = NoOpLLMClient()

    # Create registry
    registry = AgentRegistry(
        model_roster=model_roster,
        router=None,  # Will set after router creation
        breaker_registry=breaker_registry,
        queue_registry=queue_registry,
    )

    # Create router
    router = ModelRouter(
        llm_client=llm_client,
        breaker_registry=breaker_registry,
        queue_registry=queue_registry,
        retry_config=retry_config,
    )

    # Update registry with router
    registry._router = router

    # Register all agents
    for name in model_roster.agent_names:
        registry.register(name)

    # Create logger
    logger = AgentLogger()

    # Create supervisor
    supervisor = Supervisor(registry=registry, router=router, logger=logger)
    supervisor.build_graph()

    print("    [OK] Registry, router, logger, supervisor created")

    # Run analysis pipeline
    print("\n[2/6] Running analysis pipeline (BTC-USD)...")

    state = await supervisor.run_analysis(
        symbol="BTC-USD",
        request="Analyze BTC-USD for long entry opportunity"
    )

    print(f"    Session ID: {state.session_id}")
    print(f"    Request ID: {state.request_id}")
    print(f"    Pipeline status: {state.pipeline_status.current_node}")
    print(f"    Completed nodes: {state.pipeline_status.completed_nodes}")
    print(f"    Degraded: {state.degraded}")
    if state.errors:
        print(f"    Errors: {state.errors}")

    # Show agent outputs
    print("\n[3/6] Agent Outputs:")
    for agent in ["market_analyst", "quant", "news", "vision", "consensus", "risk", "execution"]:
        output = getattr(state, agent, None)
        if output:
            print(f"    {agent}: {output.model_dump_json(indent=6)}")
        else:
            print(f"    {agent}: (not executed)")

    # Create signal from consensus
    print("\n[4/6] Creating trade signal from consensus...")

    if state.consensus and state.consensus.approved:
        signal = {
            "symbol": "BTC-USD",
            "side": state.market_analyst.direction if state.market_analyst else "long",
            "quantity": 0.1,
            "order_type": "market",
            "price": 50000.0,
            "reason": f"Consensus approved: {state.consensus.rationale}",
        }
        print(f"    Signal: {signal}")
    else:
        print("    No signal generated (consensus rejected)")
        signal = None

    # Live trading engine with safety gates
    print("\n[5/6] Running through live trading engine with safety gates...")

    # Setup engine components
    kill_switch = KillSwitch(max_drawdown_pct=15.0)
    mode_manager = ModeManager(TradingMode.HUMAN_APPROVAL)
    promotion_gate = PromotionGate(min_paper_trades=10, min_paper_days=5)
    auditor = OrderAuditor()

    # Create mock exchange (no real API calls)
    exchange = MockExchangeConnector()

    engine = LiveTradingEngine(exchange, kill_switch, mode_manager, promotion_gate, auditor)

    # Set paper record to pass promotion gate
    engine.set_paper_record(10, 5)

    # Start engine
    started = await engine.start()
    print(f"    Engine started: {started}")
    print(f"    Connected: {engine.is_connected}")
    print(f"    Mode: {engine.mode.value}")
    print(f"    Paper record: {engine.paper_record}")

    # Run safety checks
    safety_results = engine.check_pre_trade()
    print(f"    Safety checks: {len(safety_results)} checks")
    for r in safety_results:
        print(f"      - Passed: {r.passed}, Reason: {r.reason}")

    if signal:
        # Try to execute with human approval mode (needs approval_id)
        result = await engine.execute_signal(signal, approval_id=None)
        print(f"    Execution result (no approval): {result}")

        # Now with approval
        result = await engine.execute_signal(signal, approval_id="test-approval-123")
        print(f"    Execution result (with approval): {result}")

    # Stop engine
    await engine.stop()
    print(f"    Engine stopped. Running: {engine.is_running}")

    # Audit log verification
    print("\n[6/6] Verifying audit log...")

    audit_entries = auditor.to_dicts(limit=10)
    print(f"    Total audit entries: {auditor.count()}")
    for i, entry in enumerate(audit_entries):
        print(f"    Entry {i+1}:")
        print(f"      Timestamp: {entry['timestamp']}")
        print(f"      Order intent: {entry['order_intent']}")
        print(f"      Agent chain: {len(entry['agent_chain'])} agents")
        for agent in entry['agent_chain']:
            print(f"        - {agent}")
        print(f"      Risk checks: {entry['risk_checks']}")
        print(f"      Order result: {entry['order_result']}")

    print("\n" + "=" * 60)
    print("SIMULATION COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())