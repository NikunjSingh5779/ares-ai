"use client";

import { useEffect, useState } from "react";
import { RefreshCw, TrendingUp, AlertTriangle } from "lucide-react";
import { MetricCard } from "@/components/MetricCard";
import { DataTable, type Column } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { PipelineFlow } from "@/components/PipelineFlow";
import { getPortfolio, getAgentStatus, getOrders, getSignal } from "@/lib/api";
import type {
  PortfolioSummary,
  AgentStatusResponse,
  ClosedTrade,
  SignalResponse,
} from "@/types/api";

export default function DashboardPage() {
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [agentStatus, setAgentStatus] = useState<AgentStatusResponse | null>(null);
  const [signal, setSignal] = useState<SignalResponse | null>(null);
  const [orders, setOrders] = useState<ClosedTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [p, a, o] = await Promise.all([
        getPortfolio().catch(() => null),
        getAgentStatus().catch(() => null),
        getOrders().catch(() => []),
      ]);
      setPortfolio(p);
      setAgentStatus(a);
      setOrders(Array.isArray(o) ? o : []);
    } catch {
      setError("Could not connect to backend");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  async function handleRunAnalysis() {
    setRunning(true);
    setError(null);
    try {
      const sig = await getSignal("BTC-USD", "Quick dashboard analysis");
      setSignal(sig);
      // Refresh portfolio and orders after signal
      const [p, a, o] = await Promise.all([
        getPortfolio().catch(() => null),
        getAgentStatus().catch(() => null),
        getOrders().catch(() => []),
      ]);
      setPortfolio(p);
      setAgentStatus(a);
      setOrders(Array.isArray(o) ? o : []);
    } catch {
      setError("Analysis request failed");
    } finally {
      setRunning(false);
    }
  }

  const orderColumns: Column<ClosedTrade>[] = [
    { key: "symbol", label: "Symbol", className: "font-medium" },
    {
      key: "side",
      label: "Side",
      render: (t) => (
        <span
          className={
            t.side === "long" ? "text-[#22c55e] font-semibold" : "text-[#ef4444] font-semibold"
          }
        >
          {t.side.toUpperCase()}
        </span>
      ),
    },
    {
      key: "pnl",
      label: "PnL",
      render: (t) => (
        <span
          className={
            t.pnl >= 0 ? "text-[#22c55e] font-medium" : "text-[#ef4444] font-medium"
          }
        >
          ${t.pnl.toFixed(2)}
        </span>
      ),
    },
    { key: "exit_reason", label: "Exit" },
    {
      key: "exit_at",
      label: "Time",
      render: (t) => new Date(t.exit_at).toLocaleString(),
    },
  ];

  if (loading && !portfolio) {
    return (
      <div className="flex items-center justify-center py-20">
        <RefreshCw size={20} className="animate-spin text-[#6366f1]" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">
            Dashboard
          </h1>
          <p className="text-label mt-1">
            Paper Trading Overview
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={loadData}
            className="btn-ghost !py-2 !px-3 !text-xs !font-mono"
          >
            <RefreshCw size={12} />
            Refresh
          </button>
          <button
            onClick={handleRunAnalysis}
            disabled={running}
            className="btn-primary !py-2 !px-3 !text-xs !font-mono disabled:opacity-50"
          >
            <TrendingUp size={12} />
            {running ? "Running..." : "Run Analysis"}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3">
          <AlertTriangle size={14} className="text-[#ef4444]" />
          <span className="font-mono text-xs text-[#ef4444]">
            {error}
          </span>
        </div>
      )}

      {/* Portfolio Summary */}
      {portfolio ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-5">
          <MetricCard
            label="Total PnL"
            value={`$${portfolio.total_pnl.toLocaleString()}`}
            change={portfolio.total_return_pct}
          />
          <MetricCard
            label="Cash"
            value={`$${portfolio.cash.toLocaleString()}`}
          />
          <MetricCard
            label="Win Rate"
            value={portfolio.win_rate.toFixed(1)}
            unit="%"
          />
          <MetricCard
            label="Trades"
            value={String(portfolio.total_trades)}
          />
          <MetricCard
            label="Max Drawdown"
            value={portfolio.max_drawdown_pct.toFixed(2)}
            unit="%"
          />
        </div>
      ) : (
        <div className="flex items-center justify-center rounded-xl border border-dashed border-[rgba(255,255,255,0.08)] p-8 bg-[rgba(255,255,255,0.02)]">
          <p className="font-mono text-sm text-[#52525b]">
            No portfolio data yet. Run an analysis to get started.
          </p>
        </div>
      )}

      {/* Pipeline & Signal */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <PipelineFlow status={agentStatus?.pipeline_status ?? null} />

        {signal && (
          <div className="card-glass">
            <p className="text-label mb-3">
              Latest Signal
            </p>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-sm text-[#a1a1aa]">
                  {signal.symbol}
                </span>
                <StatusBadge
                  status={signal.approved ? "approved" : "rejected"}
                />
              </div>
              <div className="flex items-center gap-6">
                <div>
                  <span className="text-label">
                    Direction
                  </span>
                  <p
                    className={`font-sans text-lg font-bold ${
                      signal.direction === "long"
                        ? "text-[#22c55e]"
                        : signal.direction === "short"
                          ? "text-[#ef4444]"
                          : "text-[#a1a1aa]"
                    }`}
                  >
                    {signal.direction.toUpperCase()}
                  </p>
                </div>
                <div>
                  <span className="text-label">
                    Confidence
                  </span>
                  <p className="font-sans text-lg font-bold text-white">
                    {signal.confidence.toFixed(0)}%
                  </p>
                </div>
                <div>
                  <span className="text-label">
                    Executed
                  </span>
                  <p className="font-sans text-lg font-bold text-white">
                    {signal.executed ? "Yes" : "No"}
                  </p>
                </div>
              </div>
              {signal.rationale && (
                <p className="font-mono text-xs text-[#71717a] leading-relaxed border-t border-[rgba(255,255,255,0.06)] pt-3 mt-2">
                  {signal.rationale}
                </p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Recent Trades */}
      <div>
        <h2 className="mb-3 font-sans text-sm font-semibold text-white">
          Recent Trades
        </h2>
        <DataTable
          columns={orderColumns}
          data={orders.slice(0, 10)}
          emptyMessage="No trades yet — run an analysis"
        />
      </div>
    </div>
  );
}
