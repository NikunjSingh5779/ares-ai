"""Live Market Polling Runner.

Continuously fetches the latest candle to evaluate stop-loss/take-profit,
and feeds it into the agent pipeline when a new candle closes.
"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from backend.data.ingestor import MarketDataIngestor
from backend.data.models import MarketDataRequest
from backend.routers.trading import _get_engine
from backend.routers.live import _get_engine as _get_live_engine
from database.connection import async_session_factory
from agents.supervisor import Supervisor
from agents.market_analyst import MarketAnalystAgent
from agents.quant import QuantAgent
from agents.risk import RiskAgent
from agents.execution import ExecutionAgent
from agents.journal import JournalAgent
from agents.reflection import ReflectionAgent
from agents.memory import MemoryAgent
from agents.registry import AgentRegistry
from agents.router import ModelRouter
from agents.models import load_model_roster
from agents.circuit_breaker import CircuitBreakerRegistry
from agents.queue import QueueRegistry
from agents.retry import RetryConfig
from agents.log import AgentLogger
from agents.client import create_llm_client
from configs.settings import settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ares.live")


async def _get_default_ids(session: AsyncSession) -> tuple[str, str] | None:
    """Get default paper trading account and portfolio IDs."""
    account_id = (await session.execute(text("SELECT id FROM accounts WHERE exchange='paper' LIMIT 1"))).scalar()
    if not account_id:
        return None
    portfolio_id = (await session.execute(
        text("SELECT id FROM portfolio WHERE account_id=:account_id LIMIT 1"),
        {"account_id": account_id}
    )).scalar()
    if portfolio_id:
        return str(account_id), str(portfolio_id)
    return None


async def persist_closed_trade(session: AsyncSession, trade, account_id: str, portfolio_id: str):
    """Update positions and insert into trade_history when an SL/TP is hit."""
    # Mark position closed
    await session.execute(text("""
        UPDATE positions 
        SET is_open = false, closed_at = NOW() 
        WHERE symbol = :symbol AND is_open = true AND portfolio_id = :portfolio_id
    """), {"symbol": trade.symbol, "portfolio_id": portfolio_id})
    
    # Insert trade history
    await session.execute(text("""
        INSERT INTO trade_history 
        (account_id, symbol, side, quantity, entry_price, exit_price, entry_at, exit_at, pnl, pnl_pct, is_closed, strategy_name)
        VALUES 
        (:account_id, :symbol, :side, :quantity, :entry_price, :exit_price, :entry_at, :exit_at, :pnl, :pnl_pct, true, :strategy_name)
    """), {
        "account_id": account_id,
        "symbol": trade.symbol,
        "side": trade.side,
        "quantity": trade.quantity,
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "entry_at": trade.entry_at,
        "exit_at": trade.exit_at,
        "pnl": trade.pnl,
        "pnl_pct": trade.pnl_pct,
        "strategy_name": trade.strategy_name
    })


async def main():
    logger.info("Initializing Live Runner...")
    
    ingestor = MarketDataIngestor()
    engine = _get_engine()
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
        retry_config=RetryConfig(max_retries=2, base_delay=0.5)
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
    registry.register("execution", agent=ExecutionAgent(engine=engine, session_factory=async_session_factory, live_engine=live_engine))
    registry.register("journal", agent=JournalAgent(session_factory=async_session_factory))
    registry.register("reflection", agent=ReflectionAgent())
    registry.register("memory", agent=MemoryAgent())
    registry.register("consensus")
    registry.register("vision")
    
    symbol = "ETH-USD"
    interval = "1m"
    polling_interval = 10  # Seconds
    
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
            
            # 2. Check SL/TP and Drawdown
            if live_engine:
                # We can approximate current drawdown based on paper engine for now or live portfolio
                summary = engine.get_summary()
                await live_engine.evaluate_drawdown(summary.max_drawdown_pct, symbol)
            
            closed_trades = engine.check_sl_tp(high=high_price, low=low_price)
            if closed_trades:
                async with async_session_factory() as session:
                    ids = await _get_default_ids(session)
                    if ids:
                        for trade in closed_trades:
                            logger.info(f"SL/TP Hit: Closed {trade.side} on {trade.symbol}. PnL: ${trade.pnl:.2f}")
                            await persist_closed_trade(session, trade, ids[0], ids[1])
                        await session.commit()
            
            # 3. Trigger pipeline on new candle
            if last_candle_timestamp is None or current_timestamp > last_candle_timestamp:
                logger.info(f"New candle closed at {current_timestamp}. Triggering analysis pipeline...")
                
                pipeline = Supervisor(registry=registry, router=router_model, logger=logger_instance)
                pipeline.build_graph()
                
                # Setup required memory parameters
                mem_params = {"memory": {}}
                
                async for state in pipeline.stream_analysis(symbol=symbol, request="Live analysis run"):
                    pass
                
                logger.info(f"Pipeline completed for candle {current_timestamp}.")
                
                last_candle_timestamp = current_timestamp

        except Exception as e:
            logger.error(f"Error in polling loop: {e}")
            
        await asyncio.sleep(polling_interval)


if __name__ == "__main__":
    asyncio.run(main())