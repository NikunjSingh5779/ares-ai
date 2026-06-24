"""Execution Agent — deterministic paper trade execution.

Replaces the LLM-based stub execution node in the LangGraph pipeline
with a deterministic PaperTradingEngine that simulates trade execution
without any LLM involvement.

Per AGENT I/O CONTRACTS (see CLAUDE.md):
- Input/output are strictly typed Pydantic models.
- No LLM calls — purely rule-based.
- Rationale required for explainability.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agents.state import ExecutionOutput
from agents.base import AgentContext, BaseAgent
from backend.data.models import OHLCVData
from paper_trading.engine import PaperTradingEngine
from live_trading.engine import LiveTradingEngine
from live_trading.safety import TradingMode
from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession
from sqlalchemy import text


# ---------------------------------------------------------------------------
# Input schema
# ---------------------------------------------------------------------------


class ExecutionInput(BaseModel):
    """Input for the Execution Agent.

    Receives upstream agent outputs and market data to execute a trade
    on the paper trading engine.
    """

    symbol: str = Field(..., description="Ticker symbol")
    candles: list[OHLCVData] | None = Field(
        default=None,
        description="Recent OHLCV candles (latest close = fill price)",
    )
    portfolio_value: float = Field(
        default=100000.0,
        description="Current portfolio value in USD",
    )
    market_analyst_output: dict[str, Any] | None = Field(
        default=None,
        description="MarketAnalystAgent output for direction/confidence",
    )
    risk_output: dict[str, Any] | None = Field(
        default=None,
        description="RiskAgent output for approval, stop loss, position size",
    )


# ---------------------------------------------------------------------------
# Execution Agent
# ---------------------------------------------------------------------------


class ExecutionAgent(BaseAgent[ExecutionInput, ExecutionOutput]):
    """Deterministic paper trade execution agent.

    No LLM calls — purely rule-based execution that:
    1. Checks if Risk Agent approved the trade
    2. Extracts direction from Market Analyst
    3. Gets fill price from latest candle close
    4. Calls PaperTradingEngine to simulate the trade
    5. Returns ExecutionOutput-compatible dict

    Usage::

        engine = PaperTradingEngine()
        agent = ExecutionAgent(engine=engine)
        result = await agent.run(ExecutionInput(symbol="BTC-USD", ...))
    """

    agent_name: str = "execution"
    input_schema: type[BaseModel] = ExecutionInput
    output_schema: type[BaseModel] = ExecutionOutput

    def __init__(
        self,
        engine: PaperTradingEngine,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        live_engine: LiveTradingEngine | None = None,
        context: AgentContext | None = None,
    ) -> None:
        super().__init__(context=context)
        self.engine = engine
        self.live_engine = live_engine
        self.session_factory = session_factory

    async def _get_default_ids(self, session: AsyncSession) -> tuple[str, str] | None:
        account_id = (await session.execute(text("SELECT id FROM accounts WHERE exchange='paper' LIMIT 1"))).scalar()
        if not account_id:
            return None
        portfolio_id = (await session.execute(text("SELECT id FROM portfolio WHERE account_id=:account_id LIMIT 1"), {"account_id": account_id})).scalar()
        if portfolio_id:
            return str(account_id), str(portfolio_id)
        return None

    async def process(self, inputs: ExecutionInput) -> ExecutionOutput:
        """Execute a trade signal against the paper portfolio.

        1. Validate that we have trade approval and a price to fill at.
        2. Execute the signal via the PaperTradingEngine.
        3. Return structured ExecutionOutput-compatible result.
        """
        # --- Check prerequisites ---
        if not inputs.candles:
            return ExecutionOutput(
                executed=False,
                rationale=f"No candle data available for {inputs.symbol}",
            )

        if inputs.risk_output is None:
            return ExecutionOutput(
                executed=False,
                rationale=f"No risk output received for {inputs.symbol} — rejecting trade",
            )

        risk_approved = bool(inputs.risk_output.get("approved", False))
        if not risk_approved:
            reasons = inputs.risk_output.get("reasons", [])
            rationale = "; ".join(reasons) if reasons else "Risk agent rejected trade"
            return ExecutionOutput(
                executed=False,
                rationale=f"Trade rejected by Risk Agent: {rationale}",
            )

        # --- Extract signal details ---
        if inputs.market_analyst_output is None:
            return ExecutionOutput(
                executed=False,
                rationale=f"No market analyst output for {inputs.symbol}",
            )

        direction = inputs.market_analyst_output.get("direction", "flat")
        if direction == "flat":
            return ExecutionOutput(
                executed=False,
                rationale=f"Market Analyst signal is flat for {inputs.symbol} — no trade",
            )

        # --- Fill price from latest candle close ---
        latest_candle = inputs.candles[-1]
        fill_price = float(latest_candle.close)

        if fill_price <= 0:
            return ExecutionOutput(
                executed=False,
                rationale=f"Invalid fill price ({fill_price}) for {inputs.symbol}",
            )

        # --- Quantity ---
        max_position_size = inputs.risk_output.get("max_position_size")
        stop_loss = inputs.risk_output.get("stop_loss")
        strategy_name = inputs.market_analyst_output.get("strategy_name", "")

        # Use risk's max_position_size, or default to 1 unit
        quantity = float(max_position_size) if max_position_size else 1.0

        # --- Execution Routing ---
        parts = []
        is_live_auto = False
        if self.live_engine and getattr(self.live_engine, "is_connected", False):
            if self.live_engine.mode == TradingMode.AUTO and self.live_engine.paper_record.get("promotion", {}).get("passed", False):
                is_live_auto = True

        if is_live_auto and self.live_engine is not None:
            # LIVE EXECUTION
            side_literal = "buy" if direction == "long" else "sell"
            try:
                live_order = await self.live_engine.exchange.create_order(
                    symbol=inputs.symbol,
                    side=side_literal,  # type: ignore
                    quantity=quantity,
                    order_type="market"
                )
                if live_order.status == "failed":
                    return ExecutionOutput(
                        executed=False,
                        fill_price=fill_price,
                        rationale=f"Live trade failed: {live_order.raw.get('error', 'unknown error')}",
                    )
                parts.append(f"LIVE EXECUTED {direction} position for {inputs.symbol} at market price. Order ID: {live_order.id}")
                return ExecutionOutput(
                    executed=True,
                    order_id=live_order.id,
                    fill_price=live_order.price or fill_price,
                    rationale=". ".join(parts),
                )
            except Exception as e:
                return ExecutionOutput(
                    executed=False,
                    fill_price=fill_price,
                    rationale=f"Live trade exception: {str(e)}",
                )
        else:
            # PAPER EXECUTION
            result = self.engine.execute_signal(
                symbol=inputs.symbol,
                side=direction,
                quantity=quantity,
                entry_price=fill_price,
                stop_loss=stop_loss,
                take_profit=None,
                strategy_name=strategy_name,
            )

            if not result.get("accepted", False):
                return ExecutionOutput(
                    executed=False,
                    fill_price=fill_price,
                    rationale=f"Paper trade not accepted: {result.get('reason', 'unknown')}",
                )

            position_id = result.get("position_id")
            closed_trade = result.get("closed_trade")

            parts.append(f"PAPER EXECUTED {direction} position for {inputs.symbol} at ${fill_price:.2f}")
            if result.get("reversal"):
                parts.append("(reversal — closed existing opposite position)")
            if closed_trade:
                pnl = closed_trade.get("pnl", 0)
                parts.append(f"Closed previous trade with PnL=${pnl:.2f}")

            # --- Persist to DB ---
        session_factory = getattr(self, "session_factory", None)
        if session_factory is not None and position_id:
            try:
                async with session_factory() as session:
                    ids = await self._get_default_ids(session)
                    if ids:
                        account_id, portfolio_id = ids
                        
                        # Handle reversal
                        if result.get("reversal") and closed_trade:
                            await session.execute(text("""
                                UPDATE positions 
                                SET is_open = false, closed_at = NOW() 
                                WHERE symbol = :symbol AND is_open = true AND portfolio_id = :portfolio_id
                            """), {"symbol": inputs.symbol, "portfolio_id": portfolio_id})
                            
                            await session.execute(text("""
                                INSERT INTO trade_history 
                                (account_id, symbol, side, quantity, entry_price, exit_price, entry_at, exit_at, pnl, pnl_pct, is_closed, strategy_name)
                                VALUES 
                                (:account_id, :symbol, :side, :quantity, :entry_price, :exit_price, :entry_at, NOW(), :pnl, :pnl_pct, true, :strategy_name)
                            """), {
                                "account_id": account_id,
                                "symbol": closed_trade.get("symbol"),
                                "side": closed_trade.get("side"),
                                "quantity": closed_trade.get("quantity"),
                                "entry_price": closed_trade.get("entry_price"),
                                "exit_price": closed_trade.get("exit_price"),
                                "entry_at": closed_trade.get("entry_at"),
                                "pnl": closed_trade.get("pnl"),
                                "pnl_pct": closed_trade.get("pnl_pct"),
                                "strategy_name": closed_trade.get("strategy_name", "")
                            })
                        
                        # Insert new position
                        await session.execute(text("""
                            INSERT INTO positions 
                            (id, portfolio_id, symbol, asset_type, quantity, entry_price, current_price, market_value, stop_loss, take_profit, strategy_name)
                            VALUES 
                            (:id, :portfolio_id, :symbol, 'crypto', :quantity, :entry_price, :entry_price, :market_value, :stop_loss, :take_profit, :strategy_name)
                        """), {
                            "id": position_id,
                            "portfolio_id": portfolio_id,
                            "symbol": inputs.symbol,
                            "quantity": quantity,
                            "entry_price": fill_price,
                            "market_value": quantity * fill_price,
                            "stop_loss": stop_loss,
                            "take_profit": None,
                            "strategy_name": strategy_name
                        })
                        await session.commit()
            except Exception as e:
                parts.append(f"(DB persistence failed: {str(e)})")

        return ExecutionOutput(
            executed=True,
            order_id=position_id,
            fill_price=fill_price,
            rationale=". ".join(parts),
        )
