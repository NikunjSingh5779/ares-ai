"use client";

import { useState } from "react";
import { Activity, Play, AlertCircle } from "lucide-react";
import { runBacktest } from "@/lib/api";
import type { BacktestResult, ClosedTrade } from "@/types/api";
import { MetricCard } from "@/components/MetricCard";
import { DataTable, type Column } from "@/components/DataTable";
import { EquityCurveChart } from "@/components/EquityCurveChart";

export default function BacktestPage() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BacktestResult | null>(null);

  // Form State
  const [symbol, setSymbol] = useState("BTC-USD");
  const [interval, setInterval] = useState("1d");
  const [strategy, setStrategy] = useState("momentum");
  const [daysBack, setDaysBack] = useState(365);
  const [initialCapital, setInitialCapital] = useState(100000);

  const handleRun = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const res = await runBacktest({
        symbol,
        interval,
        strategy,
        days_back: daysBack,
        initial_capital: initialCapital,
      });
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Backtest failed");
    } finally {
      setLoading(false);
    }
  };

  const columns: Column<ClosedTrade>[] = [
    { key: "symbol", label: "Symbol" },
    {
      key: "side",
      label: "Side",
      render: (t) => (
        <span
          className={
            t.side === "long" ? "text-green-500" : "text-red-500"
          }
        >
          {t.side.toUpperCase()}
        </span>
      ),
    },
    {
      key: "entry_price",
      label: "Entry",
      render: (t) => `$${t.entry_price.toLocaleString(undefined, { maximumFractionDigits: 2 })}`,
    },
    {
      key: "exit_price",
      label: "Exit",
      render: (t) => `$${t.exit_price.toLocaleString(undefined, { maximumFractionDigits: 2 })}`,
    },
    {
      key: "pnl",
      label: "PnL",
      render: (t) => (
        <span
          className={
            t.pnl >= 0 ? "text-[#22c55e]" : "text-[#ef4444]"
          }
        >
          ${t.pnl.toLocaleString(undefined, { maximumFractionDigits: 2 })}
        </span>
      ),
    },
    {
      key: "pnl_pct",
      label: "PnL %",
      render: (t) => (
        <span
          className={
            t.pnl_pct >= 0 ? "text-[#22c55e]" : "text-[#ef4444]"
          }
        >
          {t.pnl_pct.toFixed(2)}%
        </span>
      ),
    },
    {
      key: "entry_at",
      label: "Entry Time",
      render: (t) => new Date(t.entry_at).toLocaleDateString(),
    },
    {
      key: "exit_at",
      label: "Exit Time",
      render: (t) => new Date(t.exit_at).toLocaleDateString(),
    },
    { key: "exit_reason", label: "Reason" },
  ];

  return (
    <div className="flex h-full flex-col gap-6 p-6 overflow-y-auto">
      {/* Header */}
      <div className="flex flex-col gap-1 border-b border-b-[rgba(255,255,255,0.08)] pb-4">
        <h1 className="flex items-center gap-2 font-sans text-xl font-bold tracking-tight text-white">
          <Activity className="text-[#6366f1]" size={20} />
          Backtest Dashboard
        </h1>
        <p className="text-sm font-medium text-[#a1a1aa]">
          Run historical simulations and evaluate strategy performance.
        </p>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-4 gap-6">
        {/* Left Column: Form */}
        <div className="lg:col-span-1 flex flex-col gap-4">
          <form
            onSubmit={handleRun}
            className="flex flex-col gap-4 rounded-xl border border-[rgba(255,255,255,0.08)] bg-[#0a0a0a] p-5 shadow-lg"
          >
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-[#a1a1aa] uppercase tracking-wider">
                Symbol
              </label>
              <input
                type="text"
                value={symbol}
                onChange={(e) => setSymbol(e.target.value)}
                className="input-field"
                required
              />
            </div>
            
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-[#a1a1aa] uppercase tracking-wider">
                Strategy
              </label>
              <select
                value={strategy}
                onChange={(e) => setStrategy(e.target.value)}
                className="input-field"
              >
                <option value="momentum">Momentum</option>
                <option value="mean_reversion">Mean Reversion</option>
                <option value="breakout">Breakout</option>
              </select>
            </div>
            
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-[#a1a1aa] uppercase tracking-wider">
                Interval
              </label>
              <select
                value={interval}
                onChange={(e) => setInterval(e.target.value)}
                className="input-field"
              >
                <option value="1d">1 Day</option>
                <option value="1h">1 Hour</option>
                <option value="15m">15 Min</option>
              </select>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-[#a1a1aa] uppercase tracking-wider">
                Days Back
              </label>
              <input
                type="number"
                value={daysBack}
                onChange={(e) => setDaysBack(Number(e.target.value))}
                className="input-field"
                min="100"
                max="2000"
                required
              />
            </div>
            
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-[#a1a1aa] uppercase tracking-wider">
                Initial Capital ($)
              </label>
              <input
                type="number"
                value={initialCapital}
                onChange={(e) => setInitialCapital(Number(e.target.value))}
                className="input-field"
                min="1000"
                required
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn-primary mt-2"
            >
              <Play size={16} />
              {loading ? "Running Simulation..." : "Run Backtest"}
            </button>
          </form>

          {error && (
            <div className="flex items-center gap-2 rounded-lg bg-[rgba(239,68,68,0.1)] p-4 text-sm text-[#ef4444]">
              <AlertCircle size={16} />
              <p>{error}</p>
            </div>
          )}
        </div>

        {/* Right Column: Results */}
        <div className="lg:col-span-3 flex flex-col gap-6">
          {result ? (
            <>
              {/* KPIs */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricCard
                  label="Total Return"
                  value={`${result.metrics.total_return_pct.toFixed(2)}%`}
                />
                <MetricCard
                  label="Win Rate"
                  value={`${(result.metrics.win_rate * 100).toFixed(1)}%`}
                />
                <MetricCard
                  label="Max Drawdown"
                  value={`${result.metrics.max_drawdown_pct.toFixed(2)}%`}
                />
                <MetricCard
                  label="Sharpe Ratio"
                  value={result.metrics.sharpe_ratio.toFixed(2)}
                />
              </div>

              {/* Chart */}
              <EquityCurveChart equityCurve={result.equity_curve} />

              {/* Trade History */}
              <div className="flex flex-col gap-3">
                <h3 className="text-sm font-semibold text-white uppercase tracking-wider">
                  Trade History ({result.trades.length})
                </h3>
                <DataTable columns={columns} data={result.trades} emptyMessage="No trades generated during this period." />
              </div>
            </>
          ) : (
            <div className="flex h-full min-h-[400px] flex-col items-center justify-center rounded-xl border border-dashed border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.02)]">
              <Activity className="mb-4 text-[#52525b]" size={48} />
              <p className="text-sm font-medium text-[#a1a1aa]">
                Configure parameters and run a backtest to see results.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
