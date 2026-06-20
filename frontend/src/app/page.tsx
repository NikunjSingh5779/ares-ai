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
            t.side === "long"
              ? "text-[oklch(0.62_0.19_145)]"
              : "text-[oklch(0.55_0.22_30)]"
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
            t.pnl >= 0
              ? "text-[oklch(0.62_0.19_145)]"
              : "text-[oklch(0.55_0.22_30)]"
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
        <RefreshCw size={20} className="animate-spin text-[oklch(0.6_0_0)]" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-xl font-semibold text-[oklch(0.92_0_0)]">
            Dashboard
          </h1>
          <p className="font-mono text-xs text-[oklch(0.6_0_0)]">
            Paper Trading Overview
          </p>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={loadData}
            className="flex items-center gap-1.5 rounded-md border border-[oklch(0.25_0_0)] bg-[oklch(0.18_0.01_145)] px-3 py-1.5 font-mono text-xs text-[oklch(0.6_0_0)] transition-colors hover:text-[oklch(0.92_0_0)]"
          >
            <RefreshCw size={12} />
            Refresh
          </button>
          <button
            onClick={handleRunAnalysis}
            disabled={running}
            className="flex items-center gap-1.5 rounded-md bg-[oklch(0.62_0.19_145)] px-3 py-1.5 font-mono text-xs font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            <TrendingUp size={12} />
            {running ? "Running..." : "Run Analysis"}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-[oklch(0.25_0.08_30)] bg-[oklch(0.25_0.08_30)] px-4 py-2">
          <AlertTriangle size={14} className="text-[oklch(0.55_0.22_30)]" />
          <span className="font-mono text-xs text-[oklch(0.55_0.22_30)]">
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
        <div className="flex items-center justify-center rounded-lg border border-dashed border-[oklch(0.25_0_0)] p-8">
          <p className="font-mono text-sm text-[oklch(0.38_0_0)]">
            No portfolio data yet. Run an analysis to get started.
          </p>
        </div>
      )}

      {/* Pipeline & Signal */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <PipelineFlow status={agentStatus?.pipeline_status ?? null} />

        {signal && (
          <div className="rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.18_0.01_145)] p-4">
            <p className="mb-3 font-mono text-xs font-medium text-[oklch(0.6_0_0)] uppercase tracking-wider">
              Latest Signal
            </p>
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[oklch(0.6_0_0)]">
                  {signal.symbol}
                </span>
                <StatusBadge
                  status={signal.approved ? "approved" : "rejected"}
                />
              </div>
              <div className="flex items-center gap-4">
                <div>
                  <span className="font-mono text-xs text-[oklch(0.6_0_0)]">
                    Direction
                                  </span>
                  <p
                    className={`font-mono text-lg font-semibold ${
                      signal.direction === "long"
                        ? "text-[oklch(0.62_0.19_145)]"
                        : signal.direction === "short"
                          ? "text-[oklch(0.55_0.22_30)]"
                          : "text-[oklch(0.6_0_0)]"
                    }`}
                  >
                    {signal.direction.toUpperCase()}
                  </p>
                </div>
                <div>
                  <span className="font-mono text-xs text-[oklch(0.6_0_0)]">
                    Confidence
                  </span>
                  <p className="font-mono text-lg font-semibold text-[oklch(0.92_0_0)]">
                    {signal.confidence.toFixed(0)}%
                  </p>
                </div>
                <div>
                  <span className="font-mono text-xs text-[oklch(0.6_0_0)]">
                    Executed
                  </span>
                  <p className="font-mono text-lg font-semibold text-[oklch(0.92_0_0)]">
                    {signal.executed ? "Yes" : "No"}
                  </p>
                </div>
              </div>
              {signal.rationale && (
                <p className="font-mono text-xs text-[oklch(0.5_0_0)]">
                  {signal.rationale}
                </p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Recent Trades */}
      <div>
        <h2 className="mb-3 font-mono text-sm font-medium text-[oklch(0.92_0_0)]">
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
