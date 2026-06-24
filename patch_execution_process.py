import re

with open('agents/execution.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Replace the PaperTradingEngine execution with conditional Live/Paper logic
target = """        # --- Execute via PaperTradingEngine ---
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
                rationale=f"Trade not accepted: {result.get('reason', 'unknown')}",
            )

        position_id = result.get("position_id")
        closed_trade = result.get("closed_trade")

        parts = [f"Executed {direction} position for {inputs.symbol} at ${fill_price:.2f}"]
        if result.get("reversal"):
            parts.append("(reversal — closed existing opposite position)")
        if closed_trade:
            pnl = closed_trade.get("pnl", 0)
            parts.append(f"Closed previous trade with PnL=${pnl:.2f}")


        # --- Persist to DB ---"""

replacement = """        # --- Execution Routing ---
        parts = []
        is_live_auto = False
        if self.live_engine and getattr(self.live_engine, "is_connected", False):
            if self.live_engine.mode == TradingMode.AUTO and self.live_engine.promotion_gate.is_passed():
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

            # --- Persist to DB ---"""

if target in code:
    code = code.replace(target, replacement)
    with open('agents/execution.py', 'w', encoding='utf-8') as f:
        f.write(code)
    print("Execution process updated successfully.")
else:
    print("Could not find target block in execution.py")
