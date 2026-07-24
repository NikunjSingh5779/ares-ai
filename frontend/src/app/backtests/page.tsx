"use client";

import { useState } from "react";
import { RefreshCw, Play, AlertCircle, BarChart3, TrendingUp, Activity } from "lucide-react";
import { runBacktest } from "@/lib/api";
import type { BacktestResult, ClosedTrade } from "@/types/api";
import { MetricCard } from "@/components/MetricCard";
import { DataTable, type Column } from "@/components/DataTable";
import { EquityCurveChart } from "@/components/EquityCurveChart";

const SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "AAPL", "TSLA", "MSFT"];

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
          ${t.pnl.toLocaleString(undefined, { maximumFractionDigits: 2 })}
        </span>
      ),
    },
    {
      key: "pnl_pct",
      label: "P&L %",
      render: (t) => (
        <span className={`font-mono text-xs ${
          t.pnl_pct >= 0 ? "text-[#22c55e]" : "text-[#ef4444]"
        }`}>
          {t.pnl_pct.toFixed(2)}%
        </span>
      ),
    },
    {
      key: "entry_price",
      label: "Entry",
      render: (t) => <span className="font-mono text-xs text-[#a1a1aa]">${t.entry_price.toFixed(2)}</span>,
    },
    {
      key: "exit_price",
      label: "Exit",
      render: (t) => <span className="font-mono text-xs text-[#a1a1aa]">${t.exit_price.toFixed(2)}</span>,
    },
    {
      key: "entry_at",
      label: "Entered",
      render: (t) => <span className="font-mono text-xs text-[#a1a1aa]">{new Date(t.entry_at).toLocaleDateString()}</span>,
    },
    {
      key: "exit_at",
      label: "Exited",
      render: (t) => <span className="font-mono text-xs text-[#a1a1aa]">{new Date(t.exit_at).toLocaleDateString()}</span>,
    },
    { key: "exit_reason", label: "Reason" },
  ];

  const m = result?.metrics;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">
            Backtest Dashboard
          </h1>
          <p className="text-label mt-1">
            Historical Simulation & Strategy Performance
          </p>
        </div>
        {result && (
          <div className="flex items-center gap-2">
            <span className="font-mono text-[10px] text-[#52525b]">
              {result.symbol} · {result.trades.length} trades · {result.signals_generated} signals
            </span>
          </div>
        )}
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-4">
        {/* Left Column: Form */}
        <div className="lg:col-span-1 space-y-4">
          <form onSubmit={handleRun} className="card-glass space-y-4">
            <p className="text-label">Configuration</p>

            {/* Symbol */}
            <div>
              <label className="font-mono text-[10px] text-[#52525b] uppercase tracking-wider">Symbol</label>
              <div className="mt-1.5 flex flex-wrap gap-1.5">
                {SYMBOLS.map((sym) => (
                  <button
                    key={sym}
                    type="button"
                    onClick={() => setSymbol(sym)}
                    className={`rounded-lg px-2.5 py-1 font-mono text-[10px] transition-all ${
                      symbol === sym
                        ? "bg-[#6366f1] text-black font-semibold"
                        : "border border-[rgba(255,255,255,0.08)] text-[#a1a1aa] hover:border-[#6366f1]"
                    }`}
                  >
                    {sym}
                  </button>
                ))}
              </div>
            </div>

            {/* Strategy */}
            <div>
              <label className="font-mono text-[10px] text-[#52525b] uppercase tracking-wider">Strategy</label>
              <select
                value={strategy}
                onChange={(e) => setStrategy(e.target.value)}
                className="mt-1.5 w-full rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-2 font-mono text-xs text-white outline-none focus:border-[#6366f1]"
              >
                <option value="momentum" className="bg-[#1a1a1a]">Momentum</option>
                <option value="mean_reversion" className="bg-[#1a1a1a]">Mean Reversion</option>
                <option value="breakout" className="bg-[#1a1a1a]">Breakout</option>
              </select>
            </div>

            {/* Interval */}
            <div>
              <label className="font-mono text-[10px] text-[#52525b] uppercase tracking-wider">Interval</label>
              <select
                value={interval}
                onChange={(e) => setInterval(e.target.value)}
                className="mt-1.5 w-full rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-2 font-mono text-xs text-white outline-none focus:border-[#6366f1]"
              >
                <option value="1d" className="bg-[#1a1a1a]">1 Day</option>
                <option value="1h" className="bg-[#1a1a1a]">1 Hour</option>
                <option value="15m" className="bg-[#1a1a1a]">15 Min</option>
              </select>
            </div>

            {/* Days Back */}
            <div>
              <label className="font-mono text-[10px] text-[#52525b] uppercase tracking-wider">Days Back</label>
              <input
                type="number"
                value={daysBack}
                onChange={(e) => setDaysBack(Number(e.target.value))}
                min={100}
                max={2000}
                className="mt-1.5 w-full rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-2 font-mono text-xs text-white outline-none focus:border-[#6366f1]"
              />
            </div>

            {/* Initial Capital */}
            <div>
              <label className="font-mono text-[10px] text-[#52525b] uppercase tracking-wider">Initial Capital ($)</label>
              <input
                type="number"
                value={initialCapital}
                onChange={(e) => setInitialCapital(Number(e.target.value))}
                min={1000}
                className="mt-1.5 w-full rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-2 font-mono text-xs text-white outline-none focus:border-[#6366f1]"
              />
            </div>

            <button
              type="submit"
              disabled={loading}
              className="btn-primary w-full !py-2.5 !text-xs !font-mono disabled:opacity-50"
            >
              {loading ? (
                <><RefreshCw size={12} className="animate-spin" /> Running...</>
              ) : (
                <><Play size={12} /> Run Backtest</>
              )}
            </button>
          </form>

          {error && (
            <div className="flex items-center gap-2 rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3">
              <AlertCircle size={12} className="text-[#ef4444]" />
              <p className="font-mono text-xs text-[#ef4444]">{error}</p>
            </div>
          )}
        </div>

        {/* Right Column: Results */}
        <div className="lg:col-span-3 space-y-6">
          {result && m ? (
            <>
              {/* Period */}
              <div className="flex items-center gap-2 rounded-xl border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.02)] px-4 py-2.5">
                <Activity size={12} className="text-[#52525b]" />
                <span className="font-mono text-[10px] text-[#52525b]">
                  {result.start_date ? new Date(result.start_date).toLocaleDateString() : "N/A"} → {result.end_date ? new Date(result.end_date).toLocaleDateString() : "N/A"}
                </span>
                <span className="font-mono text-[10px] text-[#3f3f46]">·</span>
                <span className="font-mono text-[10px] text-[#52525b]">
                  Initial: ${m.initial_capital.toLocaleString()} → Final: ${m.final_value.toLocaleString()}
                </span>
              </div>

              {/* KPI Row 1 — Return & Risk */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricCard
                  label="Total Return"
                  value={`${m.total_return_pct >= 0 ? "+" : ""}${m.total_return_pct.toFixed(2)}%`}
                  change={m.total_return_pct}
                />
                <MetricCard
                  label="Max Drawdown"
                  value={`${m.max_drawdown_pct.toFixed(2)}%`}
                  change={m.max_drawdown_pct > 0 ? -m.max_drawdown_pct : null}
                />
                <MetricCard
                  label="Sharpe Ratio"
                  value={m.sharpe_ratio.toFixed(2)}
                  change={m.sharpe_ratio}
                />
                <MetricCard
                  label="Sortino Ratio"
                  value={m.sortino_ratio.toFixed(2)}
                  change={m.sortino_ratio}
                />
              </div>

              {/* KPI Row 2 — Trade Stats */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricCard
                  label="Win Rate"
                  value={`${(m.win_rate * 100).toFixed(1)}%`}
                  change={m.win_rate * 100}
                />
                <MetricCard
                  label="Profit Factor"
                  value={m.profit_factor.toFixed(2)}
                  change={m.profit_factor > 1 ? m.profit_factor : null}
                />
                <MetricCard
                  label="Expectancy"
                  value={m.expectancy.toFixed(2)}
                  change={m.expectancy > 0 ? m.expectancy : null}
                />
                <MetricCard
                  label="Recovery Factor"
                  value={m.recovery_factor.toFixed(2)}
                  change={m.recovery_factor > 1 ? m.recovery_factor : null}
                />
              </div>

              {/* KPI Row 3 — Volume */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                <MetricCard
                  label="Total Trades"
                  value={m.total_trades.toString()}
                />
                <MetricCard
                  label="Winning"
                  value={m.winning_trades.toString()}
                  change={m.total_trades > 0 ? (m.winning_trades / m.total_trades) * 100 : null}
                />
                <MetricCard
                  label="Losing"
                  value={m.losing_trades.toString()}
                  change={m.total_trades > 0 ? -(m.losing_trades / m.total_trades) * 100 : null}
                />
                <MetricCard
                  label="Gross P&L"
                  value={`$${(m.gross_profit - m.gross_loss).toLocaleString()}`}
                  change={m.gross_profit - m.gross_loss > 0 ? ((m.gross_profit - m.gross_loss) / m.initial_capital) * 100 : null}
                />
              </div>

              {/* Equity Curve */}
              <div className="card-glass !p-0 overflow-hidden">
                <div className="border-b border-[rgba(255,255,255,0.06)] px-5 py-4">
                  <p className="text-label">Equity Curve</p>
                </div>
                <div className="p-1">
                  <EquityCurveChart equityCurve={result.equity_curve} />
                </div>
              </div>

              {/* Trade History */}
              <div className="card-glass !p-0 overflow-hidden">
                <div className="border-b border-[rgba(255,255,255,0.06)] px-5 py-4">
                  <div className="flex items-center justify-between">
                    <p className="text-label">Trade History</p>
                    <span className="font-mono text-xs text-[#52525b]">{result.trades.length} trades</span>
                  </div>
                </div>
                <DataTable
                  columns={columns}
                  data={result.trades}
                  emptyMessage="No trades generated during this period."
                />
              </div>
            </>
          ) : (
            <div className="flex h-full min-h-[400px] flex-col items-center justify-center rounded-xl border border-dashed border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.02)]">
              <TrendingUp size={48} className="mb-4 text-[#52525b]" />
              <p className="font-mono text-sm text-[#a1a1aa]">
                Configure parameters and run a backtest to see results
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
