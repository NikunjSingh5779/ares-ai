import re

with open('agents/execution.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Imports
code = code.replace(
    'from paper_trading.engine import PaperTradingEngine',
    'from paper_trading.engine import PaperTradingEngine\nfrom sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession\nfrom sqlalchemy import text'
)

# 2. Add session_factory to __init__
code = code.replace(
    '    def __init__(\n        self,\n        engine: PaperTradingEngine,\n        context: AgentContext | None = None,\n    ) -> None:\n        super().__init__(context=context)\n        self.engine = engine',
    '    def __init__(\n        self,\n        engine: PaperTradingEngine,\n        session_factory: async_sessionmaker[AsyncSession] | None = None,\n        context: AgentContext | None = None,\n    ) -> None:\n        super().__init__(context=context)\n        self.engine = engine\n        self.session_factory = session_factory\n\n    async def _get_default_ids(self, session: AsyncSession) -> tuple[str, str] | None:\n        account_id = (await session.execute(text("SELECT id FROM accounts WHERE exchange=\'paper\' LIMIT 1"))).scalar()\n        if not account_id:\n            return None\n        portfolio_id = (await session.execute(text("SELECT id FROM portfolio WHERE account_id=:account_id LIMIT 1"), {"account_id": account_id})).scalar()\n        if portfolio_id:\n            return str(account_id), str(portfolio_id)\n        return None'
)

# 3. Change process return type
code = code.replace(
    'async def process(self, inputs: ExecutionInput) -> dict[str, Any]:',
    'async def process(self, inputs: ExecutionInput) -> ExecutionOutput:'
)

# 4. Replace dictionary returns with ExecutionOutput
code = re.sub(
    r'return \{\s*"executed": False,\s*"order_id": None,\s*"fill_price": None,\s*"filled_quantity": None,\s*"rationale": (.*?),\s*\}',
    r'return ExecutionOutput(\n                executed=False,\n                rationale=\1,\n            )',
    code,
    flags=re.DOTALL
)

code = re.sub(
    r'return \{\s*"executed": False,\s*"order_id": None,\s*"fill_price": fill_price,\s*"filled_quantity": None,\s*"rationale": (.*?),\s*\}',
    r'return ExecutionOutput(\n                executed=False,\n                fill_price=fill_price,\n                rationale=\1,\n            )',
    code,
    flags=re.DOTALL
)

# 5. Database Logic
db_logic = """
        # --- Persist to DB ---
        if getattr(self, "session_factory", None) and position_id:
            try:
                async with self.session_factory() as session:
                    ids = await self._get_default_ids(session)
                    if ids:
                        account_id, portfolio_id = ids
                        
                        # Handle reversal
                        if result.get("reversal") and closed_trade:
                            await session.execute(text(\"\"\"
                                UPDATE positions 
                                SET is_open = false, closed_at = NOW() 
                                WHERE symbol = :symbol AND is_open = true AND portfolio_id = :portfolio_id
                            \"\"\"), {"symbol": inputs.symbol, "portfolio_id": portfolio_id})
                            
                            await session.execute(text(\"\"\"
                                INSERT INTO trade_history 
                                (account_id, symbol, side, quantity, entry_price, exit_price, entry_at, exit_at, pnl, pnl_pct, is_closed, strategy_name)
                                VALUES 
                                (:account_id, :symbol, :side, :quantity, :entry_price, :exit_price, :entry_at, NOW(), :pnl, :pnl_pct, true, :strategy_name)
                            \"\"\"), {
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
                        await session.execute(text(\"\"\"
                            INSERT INTO positions 
                            (id, portfolio_id, symbol, asset_type, quantity, entry_price, current_price, market_value, stop_loss, take_profit, strategy_name)
                            VALUES 
                            (:id, :portfolio_id, :symbol, 'crypto', :quantity, :entry_price, :entry_price, :market_value, :stop_loss, :take_profit, :strategy_name)
                        \"\"\"), {
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
        )"""

code = re.sub(
    r'        return \{\s*"executed": True,\s*"order_id": position_id,\s*"fill_price": fill_price,\s*"filled_quantity": quantity,\s*"rationale": "\. "\.join\(parts\),\s*\}',
    db_logic,
    code,
    flags=re.DOTALL
)

with open('agents/execution.py', 'w', encoding='utf-8') as f:
    f.write(code)
print("Execution agent patched successfully")
