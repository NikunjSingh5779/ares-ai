"use client";

import { useEffect, useState } from "react";
import { RefreshCw, Wallet, BarChart3, BookOpen } from "lucide-react";
import { MetricCard } from "@/components/MetricCard";
import { DataTable, type Column } from "@/components/DataTable";
import { getPortfolio, getPositions, getOrders, getPaperRecord, getSignalHistory } from "@/lib/api";
import type { PortfolioSummary, OpenPosition, ClosedTrade, PaperRecord, SignalHistoryEntry } from "@/types/api";

export default function PaperTradingPage() {
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [positions, setPositions] = useState<OpenPosition[]>([]);
  const [trades, setTrades] = useState<ClosedTrade[]>([]);
  const [paperRecord, setPaperRecord] = useState<PaperRecord | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [p, pos, t, pr] = await Promise.all([
        getPortfolio().catch(() => null),
        getPositions().catch(() => []),
        getOrders().catch(() => []),
        getPaperRecord().catch(() => null),
      ]);
      setPortfolio(p);
      setPositions(Array.isArray(pos) ? pos : []);
      setTrades(Array.isArray(t) ? t : []);
      setPaperRecord(pr);
    } catch {
      setError("Could not fetch paper trading data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  const columns: Column<ClosedTrade>[] = [
    { key: "symbol", label: "Symbol" },
    {
      key: "side",
      label: "Side",
      render: (t) => (
        <span className={`font-mono text-xs font-semibold ${
          t.side === "long" ? "text-[#22c55e]" : "text-[#ef4444]"
        }`}>
          {t.side.toUpperCase()}
        </span>
      ),
    },
    {
      key: "pnl",
      label: "P&L",
      render: (t) => (
        <span className={`font-mono text-xs font-semibold ${
          t.pnl >= 0 ? "text-[#22c55e]" : "text-[#ef4444]"
        }`}>
          {t.pnl >= 0 ? "+" : ""}${t.pnl.toFixed(2)}
        </span>
      ),
    },
    { key: "entry_price", label: "Entry", render: (t) => <span className="font-mono text-xs text-[#a1a1aa]">${t.entry_price.toFixed(2)}</span> },
    { key: "exit_price", label: "Exit", render: (t) => <span className="font-mono text-xs text-[#a1a1aa]">${t.exit_price.toFixed(2)}</span> },
    { key: "exit_reason", label: "Reason" },
    { key: "strategy_name", label: "Strategy" },
  ];

  const positionColumns: Column<OpenPosition>[] = [
    { key: "symbol", label: "Symbol" },
    {
      key: "side",
      label: "Side",
      render: (p) => (
        <span className={`font-mono text-xs font-semibold ${
          p.side === "long" ? "text-[#22c55e]" : "text-[#ef4444]"
        }`}>
          {p.side.toUpperCase()}
        </span>
      ),
    },
    { key: "quantity", label: "Qty", render: (p) => <span className="font-mono text-xs text-white">{p.quantity.toFixed(4)}</span> },
    { key: "entry_price", label: "Entry Price", render: (p) => <span className="font-mono text-xs text-[#a1a1aa]">${p.entry_price.toFixed(2)}</span> },
    { key: "strategy_name", label: "Strategy" },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">Paper Trading</h1>
          <p className="text-label mt-1">Simulated Trading Environment</p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="btn-primary !py-2 !px-3 !text-xs !font-mono disabled:opacity-50"
        >
          <RefreshCw size={12} />
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3">
          <p className="font-mono text-xs text-[#ef4444]">{error}</p>
        </div>
      )}

      {/* Summary Cards */}
      {portfolio && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <MetricCard label="Initial Capital" value={`$${portfolio.initial_capital.toLocaleString()}`} />
          <MetricCard label="Cash Balance" value={`$${portfolio.cash.toLocaleString()}`} />
          <MetricCard label="Total P&L" value={`$${portfolio.total_pnl.toLocaleString()}`} change={portfolio.total_return_pct} unit="%" />
          <MetricCard label="Win Rate" value={`${portfolio.win_rate.toFixed(1)}%`} />
        </div>
      )}

      {/* Promotion Status */}
      {paperRecord && (
        <div className="card-glass">
          <div className="flex items-center justify-between mb-4">
            <p className="text-label">Paper → Live Promotion</p>
            <span
              className={`rounded-full px-2.5 py-0.5 font-mono text-xs font-semibold ${
                paperRecord.promotion.passed
                  ? "bg-[rgba(34,197,94,0.12)] text-[#22c55e]"
                  : "bg-[rgba(245,158,11,0.12)] text-[#f59e0b]"
              }`}
            >
              {paperRecord.promotion.passed ? "ELIGIBLE" : "IN PROGRESS"}
            </span>
          </div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <p className="text-label mb-1">Trade Requirement</p>
              <div className="flex items-center gap-2">
                <div className="h-2 flex-1 rounded-full bg-[rgba(255,255,255,0.06)] overflow-hidden">
                  <div
                    className="h-full rounded-full bg-[#6366f1] transition-all duration-500"
                    style={{ width: `${Math.min(100, (paperRecord.promotion.trades.current / paperRecord.promotion.trades.required) * 100)}%` }}
                  />
                </div>
                <span className="font-mono text-xs text-[#a1a1aa] min-w-[80px] text-right">
                  {paperRecord.promotion.trades.current} / {paperRecord.promotion.trades.required}
                </span>
              </div>
            </div>
            <div>
              <p className="text-label mb-1">Day Requirement</p>
              <div className="flex items-center gap-2">
                <div className="h-2 flex-1 rounded-full bg-[rgba(255,255,255,0.06)] overflow-hidden">
                  <div
                    className="h-full rounded-full bg-[#6366f1] transition-all duration-500"
                    style={{ width: `${Math.min(100, (paperRecord.promotion.days.current / paperRecord.promotion.days.required) * 100)}%` }}
                  />
                </div>
                <span className="font-mono text-xs text-[#a1a1aa] min-w-[80px] text-right">
                  {paperRecord.promotion.days.current} / {paperRecord.promotion.days.required}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Open Positions */}
      <div className="card-glass !p-0 overflow-hidden">
        <div className="border-b border-[rgba(255,255,255,0.06)] px-5 py-4">
          <div className="flex items-center justify-between">
            <p className="text-label">Open Positions</p>
            <span className="font-mono text-xs text-[#52525b]">{positions.length} positions</span>
          </div>
        </div>
        {positions.length > 0 ? (
          <DataTable columns={positionColumns} data={positions} />
        ) : (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <Wallet size={24} className="text-[#52525b] mb-3" />
            <p className="font-mono text-xs text-[#52525b]">No open positions</p>
          </div>
        )}
      </div>

      {/* Trade History */}
      <div className="card-glass !p-0 overflow-hidden">
        <div className="border-b border-[rgba(255,255,255,0.06)] px-5 py-4">
          <div className="flex items-center justify-between">
            <p className="text-label">Trade History</p>
            <span className="font-mono text-xs text-[#52525b]">{trades.length} trades</span>
          </div>
        </div>
        {trades.length > 0 ? (
          <DataTable columns={columns} data={trades} />
        ) : (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <BarChart3 size={24} className="text-[#52525b] mb-3" />
            <p className="font-mono text-xs text-[#52525b]">No trades yet</p>
          </div>
        )}
      </div>
    </div>
  );
}
