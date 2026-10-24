"""Live Market Polling Runner.

Continuously fetches the latest candle to evaluate stop-loss/take-profit,
and feeds it into the agent pipeline when a new candle closes.
"""

import asyncio
import logging

from agents.circuit_breaker import CircuitBreakerRegistry
from agents.client import create_llm_client
from agents.execution import ExecutionAgent
from agents.journal import JournalAgent
from agents.log import AgentLogger
from agents.market_analyst import MarketAnalystAgent
from agents.memory import MemoryAgent
from agents.models import load_model_roster
from agents.news import NewsAgent
from agents.quant import QuantAgent
from agents.queue import QueueRegistry
from agents.reflection import ReflectionAgent
from agents.registry import AgentRegistry
from agents.retry import RetryConfig
from agents.risk import RiskAgent
from agents.router import ModelRouter
from agents.supervisor import Supervisor
from backend.data.ingestor import MarketDataIngestor
from backend.data.models import MarketDataRequest
from backend.routers.live import _get_engine as _get_live_engine
from backend.routers.trading import get_paper_trading_ledger
from backend.services.improvement_service import record_reflection_improvement
from database.connection import async_session_factory

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ares.live")


async def main():
    logger.info("Initializing Live Runner...")

    from backend.data.repository import MarketDataRepository

    ingestor = MarketDataIngestor(repository=MarketDataRepository(session_factory=async_session_factory))
    paper_ledger = get_paper_trading_ledger()
    await paper_ledger.initialize()
    engine = paper_ledger.engine
    live_engine = _get_live_engine()

    # Resolve dependencies for Supervisor
    roster = load_model_roster()
    breaker_registry = CircuitBreakerRegistry()
    queue_registry = QueueRegistry()
    logger_instance = AgentLogger()

    llm_client = create_llm_client()

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
    registry.register("market_analyst", agent=MarketAnalystAgent(router=router_model, ingestor=ingestor))
    registry.register("quant", agent=QuantAgent(router=router_model, ingestor=ingestor))
    registry.register("risk", agent=RiskAgent(router=router_model, ingestor=ingestor))
    registry.register(
        "execution",
        agent=ExecutionAgent(
            engine=engine,
            session_factory=async_session_factory,
            live_engine=live_engine,
            ledger=paper_ledger,
        ),
    )
    registry.register("journal", agent=JournalAgent(session_factory=async_session_factory))
    registry.register("reflection", agent=ReflectionAgent())
    registry.register("memory", agent=MemoryAgent())
    registry.register("consensus")
    registry.register("vision")
    registry.register("news", agent=NewsAgent(router=router_model))

    symbol = "ETH-USD"
    interval = "1m"
    polling_interval = 60  # Seconds

    logger.info(f"Starting live polling loop for {symbol} ({interval}) every {polling_interval}s...")

    last_candle_timestamp = None

    while True:
        try:
            # 1. Fetch latest candle
            req = MarketDataRequest(symbol=symbol, source="yahoo", interval=interval, limit=1)
            result = await ingestor.ingest(req)

            if not result.candles:
                logger.warning("No data received from ingestor. Retrying...")
                await asyncio.sleep(polling_interval)
                continue

            latest_candle = result.candles[-1]
            current_timestamp = latest_candle.timestamp
            high_price = float(latest_candle.high)
            low_price = float(latest_candle.low)

            # 2. Check SL/TP and Drawdown against the durable ledger.
            closed_trades = await paper_ledger.process_candle(
                symbol=symbol,
                high=high_price,
                low=low_price,
                close=float(latest_candle.close),
            )
            if live_engine:
                summary = engine.get_summary()
                await live_engine.evaluate_drawdown(summary.max_drawdown_pct, symbol)
            for trade in closed_trades:
                logger.info(f"SL/TP Hit: Closed {trade.side} on {trade.symbol}. PnL: ${trade.pnl:.2f}")

            # 3. Trigger pipeline on new candle
            if last_candle_timestamp is None or current_timestamp > last_candle_timestamp:
                logger.info(f"New candle closed at {current_timestamp}. Triggering analysis pipeline...")

                pipeline = Supervisor(
                    registry=registry,
                    router=router_model,
                    logger=logger_instance,
                    post_run_hook=record_reflection_improvement,
                )
                pipeline.build_graph()

                async for state in pipeline.stream_analysis(symbol=symbol, request="Live analysis run"):
                    pass

                logger.info(f"Pipeline completed for candle {current_timestamp}.")

                last_candle_timestamp = current_timestamp

        except Exception as e:
            logger.error(f"Error in polling loop: {e}")

        await asyncio.sleep(polling_interval)


if __name__ == "__main__":
    asyncio.run(main())
