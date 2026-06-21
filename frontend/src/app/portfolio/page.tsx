"use client";

import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { createChart, type IChartApi, type ISeriesApi, type LineData, ColorType } from "lightweight-charts";
import { MetricCard } from "@/components/MetricCard";
import { DataTable, type Column } from "@/components/DataTable";
import { getPortfolio, getPositions, getOrders } from "@/lib/api";
import type { PortfolioSummary, OpenPosition, ClosedTrade } from "@/types/api";

export default function PortfolioPage() {
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [positions, setPositions] = useState<OpenPosition[]>([]);
  const [orders, setOrders] = useState<ClosedTrade[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartApiRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Line"> | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [p, pos, o] = await Promise.all([
        getPortfolio().catch(() => null),
        getPositions().catch(() => []),
        getOrders().catch(() => []),
      ]);
      setPortfolio(p);
      setPositions(Array.isArray(pos) ? pos : []);
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

  // Build equity curve from closed trades
  useEffect(() => {
    if (!portfolio || !chartRef.current || orders.length === 0) return;

    if (!chartApiRef.current) {
      const chart = createChart(chartRef.current, {
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: "#52525b",
          fontFamily: "JetBrains Mono, monospace",
        },
        grid: {
          vertLines: { color: "rgba(255,255,255,0.04)" },
          horzLines: { color: "rgba(255,255,255,0.04)" },
        },
        width: chartRef.current.clientWidth,
        height: 300,
        crosshair: {
          vertLine: { color: "rgba(99,102,241,0.3)", labelBackgroundColor: "#6366f1" },
          horzLine: { color: "rgba(99,102,241,0.3)", labelBackgroundColor: "#6366f1" },
        },
        timeScale: {
          borderColor: "rgba(255,255,255,0.08)",
        },
        rightPriceScale: {
          borderColor: "rgba(255,255,255,0.08)",
        },
      });

      const series = chart.addLineSeries({
        color: "#22c55e",
        lineWidth: 2,
        crosshairMarkerBackgroundColor: "#22c55e",
        crosshairMarkerBorderColor: "#22c55e",
        lastValueVisible: true,
        priceFormat: {
          type: "price",
          precision: 2,
          minMove: 0.01,
        },
      });

      chart.subscribeCrosshairMove((param) => {
        if (param.time && param.point) {
          chartRef.current?.style.setProperty("cursor", "crosshair");
        }
      });

      chartApiRef.current = chart;
      seriesRef.current = series;
    }

    // Build cumulative PnL data
    const data: LineData[] = [];
    let cumulativePnL = 0;
    data.push({ time: orders[0]?.entry_at?.split("T")[0] || "2024-01-01", value: portfolio.initial_capital });

    for (const trade of orders) {
      cumulativePnL += trade.pnl;
      const time = trade.exit_at?.split("T")[0];
      if (time) {
        data.push({ time, value: portfolio.initial_capital + cumulativePnL });
      }
    }

    seriesRef.current?.setData(data);

    const handleResize = () => {
      if (chartRef.current) {
        chartApiRef.current?.applyOptions({ width: chartRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [portfolio, orders]);

  // Cleanup chart on unmount
  useEffect(() => {
    return () => {
      chartApiRef.current?.remove();
      chartApiRef.current = null;
    };
  }, []);

  const positionColumns: Column<OpenPosition>[] = [
    { key: "symbol", label: "Symbol", className: "font-medium" },
    {
      key: "side",
      label: "Side",
      render: (p) => (
        <span className={p.side === "long" ? "text-[#22c55e] font-semibold" : "text-[#ef4444] font-semibold"}>
          {p.side.toUpperCase()}
        </span>
      ),
    },
    { key: "quantity", label: "Qty", render: (p) => p.quantity.toFixed(4) },
    {
      key: "entry_price",
      label: "Entry",
      render: (p) => `$${p.entry_price.toFixed(2)}`,
    },
    { key: "strategy_name", label: "Strategy" },
  ];

  const orderColumns: Column<ClosedTrade>[] = [
    { key: "symbol", label: "Symbol", className: "font-medium" },
    {
      key: "side",
      label: "Side",
      render: (t) => (
        <span className={t.side === "long" ? "text-[#22c55e] font-semibold" : "text-[#ef4444] font-semibold"}>
          {t.side.toUpperCase()}
        </span>
      ),
    },
    { key: "entry_price", label: "Entry", render: (t) => `$${t.entry_price.toFixed(2)}` },
    { key: "exit_price", label: "Exit", render: (t) => `$${t.exit_price.toFixed(2)}` },
    {
      key: "pnl",
      label: "PnL",
      render: (t) => (
        <span className={t.pnl >= 0 ? "text-[#22c55e] font-medium" : "text-[#ef4444] font-medium"}>
          ${t.pnl.toFixed(2)}
        </span>
      ),
    },
    { key: "exit_reason", label: "Exit" },
    {
      key: "exit_at",
      label: "Date",
      render: (t) => new Date(t.exit_at).toLocaleDateString(),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">
            Portfolio
          </h1>
          <p className="text-label mt-1">
            Paper Trading Account
          </p>
        </div>
        <button
          onClick={loadData}
          className="btn-ghost !py-2 !px-3 !text-xs !font-mono"
        >
          <RefreshCw size={12} />
          Refresh
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3">
          <span className="font-mono text-xs text-[#ef4444]">
            {error}
          </span>
        </div>
      )}

      {loading && !portfolio ? (
        <div className="flex items-center justify-center py-20">
          <RefreshCw size={20} className="animate-spin text-[#6366f1]" />
        </div>
      ) : portfolio ? (
        <>
          {/* Metrics */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <MetricCard label="Total PnL" value={`$${portfolio.total_pnl.toLocaleString()}`} change={portfolio.total_return_pct} />
            <MetricCard label="Cash Balance" value={`$${portfolio.cash.toLocaleString()}`} />
            <MetricCard label="Win Rate" value={`${portfolio.win_rate.toFixed(1)}`} unit="%" />
            <MetricCard label="Max Drawdown" value={`${portfolio.max_drawdown_pct.toFixed(2)}`} unit="%" />
          </div>

          {/* Equity Curve */}
          <div className="card-glass !p-0 overflow-hidden">
            <div className="px-6 pt-5 pb-3">
              <p className="text-label">
                Equity Curve
              </p>
            </div>
            <div ref={chartRef} className="w-full px-2 pb-2" />
            {orders.length === 0 && (
              <div className="flex items-center justify-center py-10">
                <p className="font-mono text-sm text-[#52525b]">
                  No trades yet — equity curve will appear here
                </p>
              </div>
            )}
          </div>

          {/* Open Positions */}
          <div>
            <h2 className="mb-3 font-sans text-sm font-semibold text-white">
              Open Positions ({positions.length})
            </h2>
            <DataTable
              columns={positionColumns}
              data={positions}
              emptyMessage="No open positions"
            />
          </div>

          {/* Trade History */}
          <div>
            <h2 className="mb-3 font-sans text-sm font-semibold text-white">
              Trade History ({orders.length})
            </h2>
            <DataTable
              columns={orderColumns}
              data={orders}
              emptyMessage="No closed trades yet"
            />
          </div>
        </>
      ) : (
        <div className="flex items-center justify-center rounded-xl border border-dashed border-[rgba(255,255,255,0.08)] p-12 bg-[rgba(255,255,255,0.02)]">
          <p className="font-mono text-sm text-[#52525b]">
            No portfolio data — run an analysis from the Dashboard
          </p>
        </div>
      )}
    </div>
  );
}
