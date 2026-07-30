"use client";

import { useEffect, useRef, useState } from "react";
import { RefreshCw, TrendingUp, AlertTriangle } from "lucide-react";
import { MetricCard } from "@/components/MetricCard";
import { DataTable, type Column } from "@/components/DataTable";
import { StatusBadge } from "@/components/StatusBadge";
import { PipelineFlow } from "@/components/PipelineFlow";
import { getPortfolio, getOrders } from "@/lib/api";
import { usePipelinePolling } from "@/lib/usePipelinePolling";
import type {
  PortfolioSummary,
  ClosedTrade,
} from "@/types/api";

export default function DashboardPage() {
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [orders, setOrders] = useState<ClosedTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Pipeline hook owns the full lifecycle internally.
  const { status: agentStatus, running, error: runError, timedOut, runAnalysis } = usePipelinePolling();

  // Track when the most recent analysis run finishes so we can refresh
  // portfolio/orders once per completion.
  const prevRunningRef = useRef(running);
  useEffect(() => {
    if (prevRunningRef.current && !running) {
      // Pipeline just finished → refresh derived data
      Promise.all([
        getPortfolio().catch(() => null),
        getOrders().catch(() => []),
      ]).then(([p, o]) => {
        setPortfolio(p);
        setOrders(Array.isArray(o) ? o : []);
      });
    }
    prevRunningRef.current = running;
  }, [running]);

  async function loadData() {
    setLoading(true);
    setLoadError(null);
    try {
      const [p, o] = await Promise.all([
        getPortfolio().catch(() => null),
        getOrders().catch(() => []),
      ]);
      setPortfolio(p);
      setOrders(Array.isArray(o) ? o : []);
    } catch {
      setLoadError("Could not connect to backend");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  async function handleRunAnalysis() {
    if (running) return;
    await runAnalysis("BTC-USD", "Quick dashboard analysis");
  }

  const error = loadError || runError;

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
      {timedOut && (
        <div className="flex items-center gap-2 rounded-xl border border-[rgba(255,159,28,0.2)] bg-[rgba(255,159,28,0.08)] px-4 py-3">
          <AlertTriangle size={14} className="text-[#ff9f1c]" />
          <span className="font-mono text-xs text-[#ff9f1c]">
            Pipeline timed out after 60 seconds. The analysis may still be running — check the backend logs.
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

        {agentStatus?.has_run && (agentStatus?.pipeline_status?.completed_nodes?.length ?? 0) > 0 && !running && (
          <div className="card-glass">
            <p className="text-label mb-3">
              Latest Signal Status
            </p>
            <div className="space-y-3">
              <div className="flex justify-between border-b border-[rgba(255,255,255,0.04)] pb-2 font-mono text-xs">
                <span className="text-[#a1a1aa]">Confidence</span>
                <span className="text-[#6366f1] font-bold">
                  {agentStatus?.consensus?.composite_confidence ?? "—"}%
                </span>
              </div>
              <div className="flex justify-between border-b border-[rgba(255,255,255,0.04)] pb-2 font-mono text-xs">
                <span className="text-[#a1a1aa]">Direction</span>
                <span className="text-white font-medium capitalize">
                  {agentStatus?.market_analyst?.direction ?? "—"}
                </span>
              </div>
              <div className="flex justify-between border-b border-[rgba(255,255,255,0.04)] pb-2 font-mono text-xs">
                <span className="text-[#a1a1aa]">Approved</span>
                <StatusBadge
                  status={agentStatus?.consensus?.approved ? "approved" : "rejected"}
                />
              </div>
              <div className="flex justify-between border-b border-[rgba(255,255,255,0.04)] pb-2 font-mono text-xs">
                <span className="text-[#a1a1aa]">Executed</span>
                <span className="text-white font-bold">
                  {agentStatus?.execution?.executed ? "Yes" : "No"}
                </span>
              </div>
              <div className="flex justify-between pt-1 font-mono text-xs">
                <span className="text-[#a1a1aa]">Rationale</span>
                <span className="text-[#52525b] text-right max-w-[200px] truncate" title={agentStatus?.execution?.rationale ?? "No trade"}>
                  {agentStatus?.execution?.rationale ?? "No trade"}
                </span>
              </div>
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
