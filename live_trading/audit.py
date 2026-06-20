"""Order audit logging.

Provides an append-only ``OrderAuditor`` that records every live order
with the full agent rationale chain, risk checks passed, and the final
order result. This makes all live order placement fully auditable.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AuditEntry:
    """A single audit log entry for a live order attempt.

    Attributes:
        order_intent: The signal that triggered the order (symbol, side,
            quantity, price, etc.)
        agent_chain: Ordered list of agent outputs in the pipeline
            (e.g. market_analyst, quant, risk).
        risk_checks: Results of each safety gate check that was evaluated.
        order_result: The final order result (ExchangeOrder or error).
        timestamp: When this entry was created.
    """

    order_intent: dict[str, Any]
    agent_chain: list[dict[str, Any]]
    risk_checks: list[dict[str, Any]]
    order_result: dict[str, Any] | None = None
    timestamp: datetime.datetime = field(
        default_factory=lambda: datetime.datetime.now(datetime.timezone.utc)
    )

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-compatible dict."""
        return {
            "order_intent": self.order_intent,
            "agent_chain": self.agent_chain,
            "risk_checks": self.risk_checks,
            "order_result": self.order_result,
            "timestamp": self.timestamp.isoformat(),
        }


class OrderAuditor:
    """Append-only audit log for live orders.

    Usage::

        auditor = OrderAuditor()
        auditor.record(entry)
        recent = auditor.recent(limit=20)
    """

    def __init__(self, max_entries: int = 10_000) -> None:
        self._entries: list[AuditEntry] = []
        self._max_entries = max_entries

    def record(self, entry: AuditEntry) -> None:
        """Record an audit entry.

        If the log exceeds ``max_entries``, the oldest entry is pruned.
        """
        self._entries.append(entry)
        if len(self._entries) > self._max_entries:
            self._entries.pop(0)

    def recent(self, limit: int = 50) -> list[AuditEntry]:
        """Return the most recent entries."""
        return self._entries[-limit:]

    def all(self) -> list[AuditEntry]:
        """Return all entries."""
        return list(self._entries)

    def count(self) -> int:
        """Return the total number of entries."""
        return len(self._entries)

    def clear(self) -> None:
        """Clear all entries."""
        self._entries = []

    def to_dicts(self, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent entries as serializable dicts."""
        return [e.to_dict() for e in self.recent(limit)]
