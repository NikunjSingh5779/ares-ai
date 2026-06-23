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
        context: AgentContext | None = None,
    ) -> None:
        super().__init__(context=context)
        self.engine = engine

    async def process(self, inputs: ExecutionInput) -> dict[str, Any]:
        """Execute a trade signal against the paper portfolio.

        1. Validate that we have trade approval and a price to fill at.
        2. Execute the signal via the PaperTradingEngine.
        3. Return structured ExecutionOutput-compatible result.
        """
        # --- Check prerequisites ---
        if not inputs.candles:
            return {
                "executed": False,
                "order_id": None,
                "fill_price": None,
                "filled_quantity": None,
                "rationale": f"No candle data available for {inputs.symbol}",
            }

        if inputs.risk_output is None:
            return {
                "executed": False,
                "order_id": None,
                "fill_price": None,
                "filled_quantity": None,
                "rationale": f"No risk output received for {inputs.symbol} — rejecting trade",
            }

        risk_approved = bool(inputs.risk_output.get("approved", False))
        if not risk_approved:
            reasons = inputs.risk_output.get("reasons", [])
            rationale = "; ".join(reasons) if reasons else "Risk agent rejected trade"
            return {
                "executed": False,
                "order_id": None,
                "fill_price": None,
                "filled_quantity": None,
                "rationale": f"Trade rejected by Risk Agent: {rationale}",
            }

        # --- Extract signal details ---
        if inputs.market_analyst_output is None:
            return {
                "executed": False,
                "order_id": None,
                "fill_price": None,
                "filled_quantity": None,
                "rationale": f"No market analyst output for {inputs.symbol}",
            }

        direction = inputs.market_analyst_output.get("direction", "flat")
        if direction == "flat":
            return {
                "executed": False,
                "order_id": None,
                "fill_price": None,
                "filled_quantity": None,
                "rationale": f"Market Analyst signal is flat for {inputs.symbol} — no trade",
            }

        # --- Fill price from latest candle close ---
        latest_candle = inputs.candles[-1]
        fill_price = float(latest_candle.close)

        if fill_price <= 0:
            return {
                "executed": False,
                "order_id": None,
                "fill_price": None,
                "filled_quantity": None,
                "rationale": f"Invalid fill price ({fill_price}) for {inputs.symbol}",
            }

        # --- Quantity ---
        max_position_size = inputs.risk_output.get("max_position_size")
        stop_loss = inputs.risk_output.get("stop_loss")
        strategy_name = inputs.market_analyst_output.get("strategy_name", "")

        # Use risk's max_position_size, or default to 1 unit
        quantity = float(max_position_size) if max_position_size else 1.0

        # --- Execute via PaperTradingEngine ---
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
            return {
                "executed": False,
                "order_id": None,
                "fill_price": fill_price,
                "filled_quantity": None,
                "rationale": f"Trade not accepted: {result.get('reason', 'unknown')}",
            }

        position_id = result.get("position_id")
        closed_trade = result.get("closed_trade")

        parts = [f"Executed {direction} position for {inputs.symbol} at ${fill_price:.2f}"]
        if result.get("reversal"):
            parts.append("(reversal — closed existing opposite position)")
        if closed_trade:
            pnl = closed_trade.get("pnl", 0)
            parts.append(f"Closed previous trade with PnL=${pnl:.2f}")

        return {
            "executed": True,
            "order_id": position_id,
            "fill_price": fill_price,
            "filled_quantity": quantity,
            "rationale": ". ".join(parts),
        }
