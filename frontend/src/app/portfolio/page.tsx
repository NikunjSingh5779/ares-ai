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
          textColor: "#6b7280",
        },
        grid: {
          vertLines: { color: "#1f2937" },
          horzLines: { color: "#1f2937" },
        },
        width: chartRef.current.clientWidth,
        height: 300,
        crosshair: {
          vertLine: { color: "#374151" },
          horzLine: { color: "#374151" },
        },
        timeScale: {
          borderColor: "#374151",
        },
        rightPriceScale: {
          borderColor: "#374151",
        },
      });

      const series = chart.addLineSeries({
        color: "#4ade80",
        lineWidth: 2,
        crosshairMarkerBackgroundColor: "#4ade80",
        crosshairMarkerBorderColor: "#4ade80",
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
        <span
          className={
            p.side === "long"
              ? "text-[oklch(0.62_0.19_145)]"
              : "text-[oklch(0.55_0.22_30)]"
          }
        >
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
    { key: "entry_price", label: "Entry", render: (t) => `$${t.entry_price.toFixed(2)}` },
    { key: "exit_price", label: "Exit", render: (t) => `$${t.exit_price.toFixed(2)}` },
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
      label: "Date",
      render: (t) => new Date(t.exit_at).toLocaleDateString(),
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-xl font-semibold text-[oklch(0.92_0_0)]">
            Portfolio
          </h1>
          <p className="font-mono text-xs text-[oklch(0.6_0_0)]">
            Paper Trading Account
          </p>
        </div>
        <button
          onClick={loadData}
          className="flex items-center gap-1.5 rounded-md border border-[oklch(0.25_0_0)] bg-[oklch(0.18_0.01_145)] px-3 py-1.5 font-mono text-xs text-[oklch(0.6_0_0)] transition-colors hover:text-[oklch(0.92_0_0)]"
        >
          <RefreshCw size={12} />
          Refresh
        </button>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-[oklch(0.25_0.08_30)] bg-[oklch(0.25_0.08_30)] px-4 py-2">
          <span className="font-mono text-xs text-[oklch(0.55_0.22_30)]">
            {error}
          </span>
        </div>
      )}

      {loading && !portfolio ? (
        <div className="flex items-center justify-center py-20">
          <RefreshCw size={20} className="animate-spin text-[oklch(0.6_0_0)]" />
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
          <div className="rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.13_0_0)] p-4">
            <p className="mb-3 font-mono text-xs font-medium text-[oklch(0.6_0_0)] uppercase tracking-wider">
              Equity Curve
            </p>
            <div ref={chartRef} className="w-full" />
            {orders.length === 0 && (
              <div className="flex items-center justify-center py-10">
                <p className="font-mono text-sm text-[oklch(0.38_0_0)]">
                  No trades yet — equity curve will appear here
                </p>
              </div>
            )}
          </div>

          {/* Open Positions */}
          <div>
            <h2 className="mb-3 font-mono text-sm font-medium text-[oklch(0.92_0_0)]">
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
            <h2 className="mb-3 font-mono text-sm font-medium text-[oklch(0.92_0_0)]">
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
        <div className="flex items-center justify-center rounded-lg border border-dashed border-[oklch(0.25_0_0)] p-12">
          <p className="font-mono text-sm text-[oklch(0.38_0_0)]">
            No portfolio data — run an analysis from the Dashboard
          </p>
        </div>
      )}
    </div>
  );
}
