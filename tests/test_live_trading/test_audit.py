"""Tests for the OrderAuditor and AuditEntry."""

from __future__ import annotations

import datetime

import pytest

from live_trading.audit import AuditEntry, OrderAuditor


class TestAuditEntry:
    """AuditEntry unit tests."""

    def test_create_entry(self) -> None:
        entry = AuditEntry(
            order_intent={"symbol": "BTC/USDT", "side": "buy", "quantity": 0.01},
            agent_chain=[{"agent": "market_analyst", "confidence": 0.85}],
            risk_checks=[{"check": "kill_switch", "passed": True}],
        )
        assert entry.order_intent["symbol"] == "BTC/USDT"
        assert len(entry.agent_chain) == 1
        assert len(entry.risk_checks) == 1
        assert entry.order_result is None
        assert isinstance(entry.timestamp, datetime.datetime)

    def test_entry_immutable(self) -> None:
        entry = AuditEntry(
            order_intent={},
            agent_chain=[],
            risk_checks=[],
        )
        with pytest.raises(AttributeError):
            entry.order_intent = {}  # type: ignore[misc]

    def test_to_dict(self) -> None:
        entry = AuditEntry(
            order_intent={"symbol": "ETH/USDT"},
            agent_chain=[],
            risk_checks=[],
            order_result={"status": "closed"},
        )
        d = entry.to_dict()
        assert d["order_intent"]["symbol"] == "ETH/USDT"
        assert d["order_result"]["status"] == "closed"
        assert "timestamp" in d
        assert d["timestamp"].endswith("+00:00")


class TestOrderAuditor:
    """OrderAuditor unit tests."""

    def test_record_and_count(self) -> None:
        auditor = OrderAuditor()
        assert auditor.count() == 0
        auditor.record(AuditEntry(order_intent={}, agent_chain=[], risk_checks=[]))
        assert auditor.count() == 1

    def test_recent_returns_newest_first(self) -> None:
        auditor = OrderAuditor()
        for i in range(5):
            auditor.record(
                AuditEntry(
                    order_intent={"seq": i},
                    agent_chain=[],
                    risk_checks=[],
                )
            )
        recent = auditor.recent(limit=3)
        assert len(recent) == 3
        # The 3 most recent are seq 2, 3, 4 (index 2, 3, 4 out of 0-4)
        assert recent[0].order_intent["seq"] == 2
        assert recent[1].order_intent["seq"] == 3
        assert recent[2].order_intent["seq"] == 4

    def test_all_returns_everything(self) -> None:
        auditor = OrderAuditor()
        for i in range(3):
            auditor.record(AuditEntry(order_intent={"seq": i}, agent_chain=[], risk_checks=[]))
        assert len(auditor.all()) == 3

    def test_clear(self) -> None:
        auditor = OrderAuditor()
        for i in range(3):
            auditor.record(AuditEntry(order_intent={}, agent_chain=[], risk_checks=[]))
        auditor.clear()
        assert auditor.count() == 0

    def test_max_entries_prunes_oldest(self) -> None:
        auditor = OrderAuditor(max_entries=3)
        for i in range(5):
            auditor.record(
                AuditEntry(
                    order_intent={"seq": i},
                    agent_chain=[],
                    risk_checks=[],
                )
            )
        assert auditor.count() == 3
        # The first two entries (seq 0, 1) should be pruned
        entries = auditor.all()
        seqs = [e.order_intent["seq"] for e in entries]
        assert seqs == [2, 3, 4]

    def test_to_dicts(self) -> None:
        auditor = OrderAuditor()
        auditor.record(
            AuditEntry(
                order_intent={"symbol": "SOL/USDT"},
                agent_chain=[],
                risk_checks=[],
            )
        )
        dicts = auditor.to_dicts()
        assert len(dicts) == 1
        assert dicts[0]["order_intent"]["symbol"] == "SOL/USDT"
