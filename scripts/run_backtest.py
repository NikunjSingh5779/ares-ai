#!/usr/bin/env python
"""True Walk-Forward Backtest Runner.

This script fetches historical market data and runs it through the actual
Agent Pipeline (Supervisor -> Market Analyst -> Quant -> ... -> Execution).
It processes the data step-by-step (walk-forward) to prevent look-ahead bias.

Signals are collected and executed via BacktestEngine to prove the strategy's
real performance before unlocking the Promotion Gate.
"""

import asyncio
import sys
import os
import argparse
from datetime import datetime, timedelta, UTC

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from backend.data.ingestor import MarketDataIngestor
from backend.data.models import MarketDataRequest, Interval, Source
from backend.core.config import settings
from backtesting.engine import BacktestEngine, BacktestInput

from agents.supervisor import Supervisor
from agents.registry import AgentRegistry
from agents.router import ModelRouter
from agents.log import AgentLogger
from agents.state import AgentState
from agents.models import load_model_roster
from agents.circuit_breaker import CircuitBreakerRegistry
from agents.queue import QueueRegistry
from agents.retry import RetryConfig
from agents.client import LLMClient, create_llm_client

from agents.market_analyst import MarketAnalystAgent
from agents.quant import QuantAgent
from agents.risk import RiskAgent
from agents.execution import ExecutionAgent
from agents.journal import JournalAgent
from agents.reflection import ReflectionAgent
from agents.memory import MemoryAgent


async def main():
    parser = argparse.ArgumentParser(description="ARES AI: Walk-Forward Backtest Runner")
    parser.add_argument("--limit", type=int, default=5, help="Number of candles to test")
    args = parser.parse_args()

    print("=== ARES AI: Walk-Forward Backtest Runner ===")
    
    print("\n[1] Initializing Agent Pipeline...")
    
    roster = load_model_roster()
    breaker_registry = CircuitBreakerRegistry()
    queue_registry = QueueRegistry()
    logger = AgentLogger()
    
    llm_client = create_llm_client()
    if isinstance(llm_client, LLMClient) and not llm_client.providers:
        print("    [!] WARNING: No API key configured. Pipeline will run in degraded mode (rule-based fallback).")
    
    router_model = ModelRouter(
        llm_client=llm_client,
        breaker_registry=breaker_registry,
        queue_registry=queue_registry,
        retry_config=RetryConfig(max_retries=2, base_delay=0.5),
    )
    
    registry = AgentRegistry(
        model_roster=roster,
        router=router_model,
        breaker_registry=breaker_registry,
        queue_registry=queue_registry,
    )

    shared_ingestor = MarketDataIngestor()

    registry.register("market_analyst", agent=MarketAnalystAgent(router=router_model, ingestor=shared_ingestor))
    registry.register("quant", agent=QuantAgent(router=router_model, ingestor=shared_ingestor))
    registry.register("risk", agent=RiskAgent(router=router_model, ingestor=shared_ingestor))
    registry.register("execution", agent=ExecutionAgent(engine=None))  # execution agent mock for backtesting
    registry.register("journal", agent=JournalAgent())
    registry.register("reflection", agent=ReflectionAgent())
    registry.register("memory", agent=MemoryAgent())
    
    # Register any missing stubs
    for name in roster.agent_names:
        try:
            registry.get(name)
        except KeyError:
            registry.register(name)
    
    supervisor = Supervisor(registry=registry, router=router_model, logger=logger)
    supervisor.build_graph()

    print("[2] Fetching historical market data for ETH-USD...")
    ingestor = MarketDataIngestor()
    end_date = datetime.now(UTC)
    start_date = end_date - timedelta(days=365)
    
    req = MarketDataRequest(
        symbol="ETH-USD",
        interval=Interval.DAY_1,
        source=Source.BINANCE,
        start_date=start_date,
        end_date=end_date,
        limit=1000,
    )
    result = await ingestor.ingest(req)
    candles = result.candles
    print(f"    Loaded {len(candles)} historical candles.")

    if len(candles) < 50:
        print("    Not enough data. Exiting.")
        return

    lookback = 40
    total_to_test = min(args.limit, len(candles) - lookback)
    test_candles = candles[-(total_to_test + lookback):]
    
    print(f"\n[3] Running true walk-forward simulation on last {total_to_test} candles...")
    signals = []
    confidence_distribution = {"ma": [], "quant": []}
    dual_consensus_count = 0

    for i in range(lookback, len(test_candles)):
        current_idx = i
        window = test_candles[:current_idx+1]
        current_candle = window[-1]

        print(f"    Step {i - lookback + 1}/{total_to_test} | Candle: {current_candle.timestamp}")
        
        state = AgentState(
            symbol="ETH-USD",
            request="Analyze historical step",
        )
        state.candles = window

        out_state = await supervisor.run(initial_state=state)

        if out_state.consensus and out_state.consensus.approved and out_state.market_analyst:
            direction = out_state.market_analyst.direction
            tp = None
            sl = None
            if out_state.quant and out_state.quant.params:
                sl_pct = out_state.quant.params.get("stop_loss_pct", 5.0) / 100.0
                sl = current_candle.close * (1 - sl_pct) if direction == "long" else current_candle.close * (1 + sl_pct)
                expected_return = getattr(out_state.quant, "expected_return", 5.0) / 100.0
                tp = current_candle.close * (1 + expected_return) if direction == "long" else current_candle.close * (1 - expected_return)

            signal = {
                "direction": direction,
                "timestamp": current_candle.timestamp,
                "strategy_name": "ARES_Pipeline",
                "entry_price": current_candle.close,
                "take_profit": tp,
                "stop_loss": sl,
                "confidence": out_state.consensus.composite_confidence
            }
            signals.append(signal)
            dual_consensus_count += 1
            print(f"      -> GENERATED SIGNAL: {direction.upper()} at {current_candle.close}")
        else:
            reason = "No signal"
            if out_state.errors:
                reason = f"Pipeline degraded/errors: {out_state.errors}"
            elif out_state.consensus and not out_state.consensus.approved:
                reason = "Consensus Rejected"
            
            ma_conf = getattr(out_state.market_analyst, "confidence", 0.0) if out_state.market_analyst else 0.0
            q_conf = getattr(out_state.quant, "confidence", 0.0) if out_state.quant else 0.0
            print(f"      -> {reason} | MA Conf: {ma_conf:.1f}%, Quant Conf: {q_conf:.1f}%")

        ma_conf = getattr(out_state.market_analyst, "confidence", 0.0) if out_state.market_analyst else 0.0
        q_conf = getattr(out_state.quant, "confidence", 0.0) if out_state.quant else 0.0
        confidence_distribution["ma"].append(ma_conf)
        confidence_distribution["quant"].append(q_conf)

    print(f"\n[4] Running BacktestEngine with {len(signals)} true signals...")
    engine = BacktestEngine()
    backtest_input = BacktestInput(
        symbol="ETH-USD",
        candles=test_candles,
        initial_capital=100000.0,
        commission_pct=0.001,
        slippage_pct=0.001,
        signals=signals,
    )
    
    report = engine.run(backtest_input)
    
    metrics = report.metrics
    print("\n=== True Backtest Complete ===")
    print(f"Symbol:          {report.symbol}")
    print(f"Initial Capital: ${metrics.get('initial_capital'):,.2f}")
    print(f"Final Capital:   ${metrics.get('final_value'):,.2f}")
    print(f"Total Return:    {metrics.get('total_return_pct'):.2f}%")
    print(f"Total Trades:    {metrics.get('total_trades')}")
    print(f"Win Rate:        {metrics.get('win_rate'):.2f}%")
    print(f"Max Drawdown:    {metrics.get('max_drawdown_pct'):.2f}%")
    print(f"Profit Factor:   {metrics.get('profit_factor'):.2f}")
    
    ma_confs = confidence_distribution['ma']
    q_confs = confidence_distribution['quant']
    avg_ma = sum(ma_confs) / len(ma_confs) if ma_confs else 0.0
    avg_q = sum(q_confs) / len(q_confs) if q_confs else 0.0
    print("\n--- Confidence Distribution ---")
    print(f"Market Analyst Average: {avg_ma:.1f}%")
    print(f"Quant Average:          {avg_q:.1f}%")
    print(f"80%+ Dual Consensus Occurrences: {dual_consensus_count}")
    print("==============================")
    
    if metrics.get('total_trades', 0) >= 50 and metrics.get('total_return_pct', 0) > 0:
        print("\n[SUCCESS] PROMOTION GATE CRITERIA MET!")
        print("          (> 50 trades and positive PnL achieved)")
    else:
        print("\n[FAILED] Promotion gate criteria not met (need 50 trades + positive PnL).")

    # Gracefully close all HTTPX clients and flush journal
    await llm_client.close()
    
    journal_agent = registry.get("journal")
    if journal_agent and hasattr(journal_agent, "writer"):
        await journal_agent.writer.flush_remaining()


if __name__ == "__main__":
    asyncio.run(main())
