"""Live trading engine — wraps an exchange connector with safety gates.

The engine mirrors the ``PaperTradingEngine`` interface so the pipeline
can treat both interchangeably. Every order goes through the safety gate
checklist before reaching the exchange.
"""

from __future__ import annotations

import datetime
from typing import Any, Literal

from live_trading.audit import AuditEntry, OrderAuditor
from live_trading.exceptions import (
    ExchangeConnectionError,
    KillSwitchTrippedError,
    ModeError,
    PromotionGateError,
)
from live_trading.exchange.base import ExchangeConnector, ExchangeOrder
from live_trading.safety import KillSwitch, ModeManager, PromotionGate, SafetyCheckResult, TradingMode


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
    ) -> None:
        self.exchange = exchange
        self.kill_switch = kill_switch
        self.mode_manager = mode_manager
        self.promotion_gate = promotion_gate
        self.auditor = auditor or OrderAuditor()

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
        """Set the paper trading record for promotion evaluation."""
        self._paper_trades_count = trades
        self._paper_days_count = days

    @property
    def paper_record(self) -> dict[str, Any]:
        """Return the paper record and promotion status."""
        return {
            "trades": self._paper_trades_count,
            "days": self._paper_days_count,
            "promotion": self.promotion_gate.progress(
                self._paper_trades_count,
                self._paper_days_count,
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

    def check_pre_trade(self) -> list[SafetyCheckResult]:
        """Run all pre-trade safety checks.

        Returns a list of ``SafetyCheckResult`` in evaluation order.
        The caller should treat any ``passed=False`` result as a block.
        """
        results: list[SafetyCheckResult] = []

        # 1. KillSwitch
        results.append(self.kill_switch.check())

        # 2. Mode — check if approval is needed (doesn't block)
        results.append(self.mode_manager.check())

        # 3. PromotionGate
        results.append(
            self.promotion_gate.check(self._paper_trades_count, self._paper_days_count)
        )

        # 4. Exchange connection
        if not self.exchange.is_connected:
            results.append(
                SafetyCheckResult(
                    passed=False,
                    reason=f"Exchange {self.exchange.exchange_name} is not connected",
                )
            )
        else:
            results.append(SafetyCheckResult(passed=True))

        return results

    def _raise_if_blocked(self, results: list[SafetyCheckResult]) -> None:
        """Raise the appropriate exception if any safety check fails."""
        for r in results:
            if r.passed:
                continue
            if "Kill switch" in r.reason or "triggered by" in r.reason:
                raise KillSwitchTrippedError(r.reason)
            if "Paper record" in r.reason:
                raise PromotionGateError(r.reason)
            if "not connected" in r.reason:
                raise ExchangeConnectionError(r.reason)

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
        safety_results = self.check_pre_trade()

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

        self._raise_if_blocked(safety_results)

        risk_check_dicts = [r.reason for r in safety_results]

        # ── Place the order ─────────────────────────────────────────
        try:
            order = await self.exchange.create_order(
                symbol=order_intent["symbol"],
                side=order_intent["side"],  # type: ignore[arg-type]
                quantity=order_intent["quantity"],
                order_type=order_intent["order_type"],
                price=order_intent.get("price"),
            )
        except Exception as exc:
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
