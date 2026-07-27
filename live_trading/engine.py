"""Live trading engine — wraps an exchange connector with safety gates.

The engine mirrors the ``PaperTradingEngine`` interface so the pipeline
can treat both interchangeably. Every order goes through the safety gate
checklist before reaching the exchange.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import text

from backend.core.metrics import record_live_order
from live_trading.audit import AuditEntry, OrderAuditor
from live_trading.exceptions import (
    ExchangeConnectionError,
    KillSwitchTrippedError,
    ModeError,
    PromotionGateError,
)
from live_trading.exchange.base import ExchangeConnector
from live_trading.safety import (
    KillSwitch,
    ModeManager,
    PromotionGate,
    SafetyCheckResult,
    TradingMode,
)

logger = logging.getLogger(__name__)


class LiveTradingEngine:
    """Live trading engine wrapping an exchange connector with safety gates.

    Safety gate order (evaluated before every trade)::

        1. KillSwitch active?          → BLOCK
        2. Mode = human_approval?      → require explicit approval
        3. PromotionGate passed?       → BLOCK if insufficient paper record
        4. Exchange connected?         → BLOCK if disconnected
        5. (RiskAgent check done upstream by the pipeline)

    Usage::

        engine = LiveTradingEngine(exchange, kill_switch, mode_manager, promotion_gate)
        await engine.start()
        result = await engine.execute_signal(signal_data, agent_chain=...)
        await engine.stop()
    """

    def __init__(
        self,
        exchange: ExchangeConnector,
        kill_switch: KillSwitch,
        mode_manager: ModeManager,
        promotion_gate: PromotionGate,
        auditor: OrderAuditor | None = None,
        session_factory: Any = None,
    ) -> None:
        self.exchange = exchange
        self.kill_switch = kill_switch
        self.mode_manager = mode_manager
        self.promotion_gate = promotion_gate
        self.auditor = auditor or OrderAuditor()
        self._session_factory = session_factory

        self._running = False
        self._paper_trades_count = 0
        self._paper_days_count = 0

    # ── Properties ──────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        """Whether the engine is currently running."""
        return self._running

    @property
    def is_connected(self) -> bool:
        """Whether the underlying exchange connector is connected."""
        return self.exchange.is_connected

    @property
    def mode(self) -> TradingMode:
        """Current trading mode."""
        return self.mode_manager.mode

    # ── Paper record (for promotion gate) ───────────────────────────

    def set_paper_record(self, trades: int, days: int) -> None:
        """Set the paper trading record for promotion evaluation (in-memory fallback)."""
        self._paper_trades_count = trades
        self._paper_days_count = days

    async def _query_paper_record_from_db(
        self,
        account_id: str | None = None,
        strategy_name: str | None = None,
    ) -> dict[str, Any]:
        """Query paper trading stats — including risk quality — from the database.

        Accepts optional ``account_id`` and ``strategy_name`` filters.
        Returns a dict with keys ``trades``, ``days``, ``total_pnl``, and
        ``max_drawdown_pct``. ``total_pnl``/``max_drawdown_pct`` are ``None``
        when unavailable (no DB configured, or a DB error) — this is a
        *degraded*, not a safer, mode: the ``PromotionGate`` skips risk-quality
        checks it cannot evaluate, so callers should prefer the DB-backed path
        whenever real promotion decisions are made.

        Note: ``max_drawdown_pct`` reflects the paper account's overall
        portfolio drawdown (from the ``portfolio`` table), not a strategy-only
        drawdown — the schema does not track per-strategy equity curves. If
        multiple strategies share one paper account, this is an approximation.
        """
        if not self._session_factory:
            return {
                "trades": self._paper_trades_count,
                "days": self._paper_days_count,
                "total_pnl": None,
                "max_drawdown_pct": None,
            }

        try:
            async with self._session_factory() as session:
                params: dict[str, Any] = {}
                filters: list[str] = []

                if account_id:
                    filters.append("AND th.account_id = :account_id")
                    params["account_id"] = account_id
                if strategy_name:
                    filters.append("AND th.strategy_name = :strategy_name")
                    params["strategy_name"] = strategy_name

                filter_clause = " ".join(filters)

                trades_count = (
                    await session.execute(
                        text(f"""
                    SELECT COUNT(*) FROM trade_history th
                    JOIN accounts a ON th.account_id = a.id
                    WHERE a.exchange = 'paper' AND th.is_closed = true
                    {filter_clause}
                """),
                        params,
                    )
                ).scalar() or 0

                days_count = (
                    await session.execute(
                        text(f"""
                    SELECT COUNT(DISTINCT DATE(entry_at)) FROM trade_history th
                    JOIN accounts a ON th.account_id = a.id
                    WHERE a.exchange = 'paper'
                    {filter_clause}
                """),
                        params,
                    )
                ).scalar() or 0

                total_pnl_raw = (
                    await session.execute(
                        text(f"""
                    SELECT COALESCE(SUM(th.pnl), 0) FROM trade_history th
                    JOIN accounts a ON th.account_id = a.id
                    WHERE a.exchange = 'paper' AND th.is_closed = true
                    {filter_clause}
                """),
                        params,
                    )
                ).scalar()
                total_pnl = float(total_pnl_raw) if total_pnl_raw is not None else 0.0

                # Portfolio-level drawdown — not strategy-scoped (see docstring).
                account_filter = ""
                account_params: dict[str, Any] = {}
                if account_id:
                    account_filter = "AND a.id = :account_id"
                    account_params["account_id"] = account_id

                max_dd_raw = (
                    await session.execute(
                        text(f"""
                    SELECT MAX(p.max_drawdown_pct) FROM portfolio p
                    JOIN accounts a ON p.account_id = a.id
                    WHERE a.exchange = 'paper'
                    {account_filter}
                """),
                        account_params,
                    )
                ).scalar()
                max_drawdown_pct = float(max_dd_raw) if max_dd_raw is not None else None

                return {
                    "trades": int(trades_count),
                    "days": int(days_count),
                    "total_pnl": total_pnl,
                    "max_drawdown_pct": max_drawdown_pct,
                }
        except Exception:
            logger.exception("Failed to query paper record from DB, falling back to in-memory")
            return {
                "trades": self._paper_trades_count,
                "days": self._paper_days_count,
                "total_pnl": None,
                "max_drawdown_pct": None,
            }

    async def paper_record(
        self,
        account_id: str | None = None,
        strategy_name: str | None = None,
    ) -> dict[str, Any]:
        """Return the paper record and promotion status.

        Queries the database when a session factory is available.
        Falls back to in-memory values otherwise.
        Supports optional per-account and per-strategy isolation.
        """
        record = await self._query_paper_record_from_db(account_id, strategy_name)
        trades, days = record["trades"], record["days"]
        return {
            "trades": trades,
            "days": days,
            "total_pnl": record["total_pnl"],
            "max_drawdown_pct": record["max_drawdown_pct"],
            "promotion": self.promotion_gate.progress(
                trades,
                days,
                total_pnl=record["total_pnl"],
                max_drawdown_pct=record["max_drawdown_pct"],
            ),
        }

    # ── Lifecycle ───────────────────────────────────────────────────

    async def start(self) -> bool:
        """Connect to the exchange and start the engine.

        Returns:
            True if the engine started successfully.
        """
        connected = await self.exchange.connect()
        if connected:
            self._running = True
        return connected

    async def stop(self) -> None:
        """Disconnect from the exchange and stop the engine."""
        await self.exchange.disconnect()
        self._running = False

    # ── Safety check ────────────────────────────────────────────────

    async def check_pre_trade(self, account_id: str | None = None) -> list[SafetyCheckResult]:
        """Run all pre-trade safety checks.

        Accepts an optional ``account_id`` for per-account promotion gate isolation.
        Returns a list of ``SafetyCheckResult`` in evaluation order.
        The caller should treat any ``passed=False`` result as a block.
        """
        results: list[SafetyCheckResult] = []

        # 1. KillSwitch
        results.append(self.kill_switch.check())

        # 2. Mode — check if approval is needed (doesn't block)
        results.append(self.mode_manager.check())

        # 3. PromotionGate — DB-backed with per-account isolation, including risk quality
        record = await self._query_paper_record_from_db(account_id)
        results.append(
            self.promotion_gate.check(
                record["trades"],
                record["days"],
                total_pnl=record["total_pnl"],
                max_drawdown_pct=record["max_drawdown_pct"],
            )
        )

        # 4. Exchange connection
        if not self.exchange.is_connected:
            results.append(
                SafetyCheckResult(
                    passed=False,
                    reason=f"Exchange {self.exchange.exchange_name} is not connected",
                    code="exchange",
                )
            )
        else:
            results.append(SafetyCheckResult(passed=True, code="exchange"))

        return results

    _CODE_TO_EXCEPTION: dict[str, type[Exception]] = {
        "kill_switch": KillSwitchTrippedError,
        "promotion_gate": PromotionGateError,
        "exchange": ExchangeConnectionError,
        "mode": ModeError,
    }

    def _raise_if_blocked(self, results: list[SafetyCheckResult]) -> None:
        """Raise the appropriate exception if any safety check fails.

        Branches on ``SafetyCheckResult.code`` — a stable, typed identifier —
        rather than parsing ``reason`` text. This guarantees that a future
        rewording of a reason message can never silently disable a gate and
        let a blocked trade fall through to order placement (see AGENTS.md:
        "No silent trade approval on agent failure"). Any failing result
        with an unrecognized code still raises, fail-closed, rather than
        being ignored.
        """
        for r in results:
            if r.passed:
                continue
            exc_type = self._CODE_TO_EXCEPTION.get(r.code)
            if exc_type is not None:
                raise exc_type(r.reason)
            # Unknown/unmapped failure code — fail closed rather than
            # silently allowing the order to proceed.
            raise RuntimeError(f"Unrecognized safety check failure (code={r.code!r}): {r.reason}")

    # ── Order execution ─────────────────────────────────────────────

    async def execute_signal(
        self,
        signal: dict[str, Any],
        agent_chain: list[dict[str, Any]] | None = None,
        risk_checks: list[dict[str, Any]] | None = None,
        approval_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a trading signal through the safety gates.

        Args:
            signal: Signal dict with keys ``symbol``, ``side``, ``quantity``,
                ``order_type``, ``price`` (optional), ``reason`` (optional).
            agent_chain: Ordered list of agent outputs that produced this signal.
            risk_checks: Results of risk agent checks from the pipeline.
            approval_id: Human approval ID if mode requires it.

        Returns:
            Dict with keys ``accepted`` (bool), ``reason`` (str), and
            ``order`` (ExchangeOrder dict or None).

        Raises:
            KillSwitchTrippedError: If kill switch is active.
            PromotionGateError: If paper record is insufficient.
            ExchangeConnectionError: If exchange is not connected.
        """
        order_intent: dict[str, Any] = {
            "symbol": signal.get("symbol", ""),
            "side": signal.get("side", ""),
            "quantity": signal.get("quantity", 0),
            "order_type": signal.get("order_type", "market"),
            "price": signal.get("price"),
            "reason": signal.get("reason", ""),
        }

        # ── Pre-trade safety check ──────────────────────────────────
        safety_results = await self.check_pre_trade(signal.get("account_id"))

        # Check if human approval is needed
        if self.mode_manager.requires_approval() and not approval_id:
            safety_entry = AuditEntry(
                order_intent=order_intent,
                agent_chain=agent_chain or [],
                risk_checks=risk_checks or [],
                order_result={"status": "pending_approval"},
            )
            self.auditor.record(safety_entry)

            return {
                "accepted": False,
                "reason": "Human approval required — provide approval_id to proceed",
                "order": None,
            }

        # If approval_id is provided, filter out the mode check from safety results
        # since approval has been granted
        if approval_id:
            safety_results = [r for r in safety_results if not (r.code == "mode" and not r.passed)]

        self._raise_if_blocked(safety_results)

        # ── Place the order ─────────────────────────────────────────
        try:
            order = await self.exchange.create_order(
                symbol=order_intent["symbol"],
                side=order_intent["side"],
                quantity=order_intent["quantity"],
                order_type=order_intent["order_type"],
                price=order_intent.get("price"),
            )
        except Exception as exc:
            record_live_order("error")
            error_entry = AuditEntry(
                order_intent=order_intent,
                agent_chain=agent_chain or [],
                risk_checks=risk_checks or [],
                order_result={"status": "error", "error": str(exc)},
            )
            self.auditor.record(error_entry)
            raise

        # ── Record success ──────────────────────────────────────────
        order_dict = {
            "id": order.id,
            "symbol": order.symbol,
            "side": order.side,
            "type": order.type,
            "quantity": order.quantity,
            "price": order.price,
            "filled": order.filled,
            "remaining": order.remaining,
            "status": order.status,
        }

        record_live_order(str(order_dict["status"]))

        entry = AuditEntry(
            order_intent=order_intent,
            agent_chain=agent_chain or [],
            risk_checks=risk_checks or [],
            order_result=order_dict,
        )
        self.auditor.record(entry)

        return {
            "accepted": True,
            "reason": "Order placed successfully",
            "order": order_dict,
        }

    async def evaluate_drawdown(self, current_drawdown_pct: float, symbol: str) -> bool:
        """Evaluate if drawdown breached the kill switch threshold.

        If it does:
        1. Force TradingMode to PAPER.
        2. Emit emergency log.
        3. Attempt to cancel all open orders for the symbol.
        """
        import logging

        logger = logging.getLogger("ares")

        tripped = self.kill_switch.auto_trigger(current_drawdown_pct)
        if tripped:
            self.mode_manager.set_mode(TradingMode.HUMAN_APPROVAL)
            logger.critical(
                f"EMERGENCY: Kill Switch tripped due to {current_drawdown_pct:.1f}% drawdown! "
                "Mode forced to HUMAN_APPROVAL."
            )
            try:
                if self.is_connected and hasattr(self.exchange, "cancel_all_orders"):
                    await self.exchange.cancel_all_orders(symbol)
                    logger.critical(f"EMERGENCY: All open orders for {symbol} cancelled successfully.")
            except Exception as e:
                logger.error(f"Failed to cancel open orders during emergency halt: {e}")
            return True
        return False

    # ── Inspection ──────────────────────────────────────────────────

    # ── Convenience wrappers ────────────────────────────────────────

    async def get_balance(self) -> dict[str, float]:
        """Fetch current exchange balance."""
        if not self.exchange.is_connected:
            raise ExchangeConnectionError("Exchange is not connected")
        balance = await self.exchange.get_balance()
        return balance.total

    async def get_open_orders(self) -> list[dict[str, Any]]:
        """Fetch open orders (limited — uses get_order_status per known order).

        For a real implementation, use exchange.fetch_open_orders().
        """
        return []

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """Cancel an order on the exchange."""
        if not self.exchange.is_connected:
            raise ExchangeConnectionError("Exchange is not connected")
        return await self.exchange.cancel_order(order_id, symbol)
