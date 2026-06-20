"use client";

import { useEffect, useRef, useState } from "react";
import { RefreshCw, TrendingUp } from "lucide-react";
import { createChart, type IChartApi, type ISeriesApi, type CandlestickData, ColorType } from "lightweight-charts";
import { analyze } from "@/lib/api";
import type { AgentState } from "@/types/api";

const SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "AAPL", "TSLA", "MSFT"];

export default function MarketsPage() {
  const [symbol, setSymbol] = useState("BTC-USD");
  const [analysis, setAnalysis] = useState<AgentState | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartApiRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  async function runAnalysis() {
    setLoading(true);
    setError(null);
    try {
      const result = await analyze(symbol);
      setAnalysis(result);
    } catch {
      setError(`Analysis failed for ${symbol}`);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    runAnalysis();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  // Generate dummy price chart data for visualization
  useEffect(() => {
    if (!chartRef.current) return;

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
        height: 400,
        crosshair: {
          vertLine: { color: "#374151" },
          horzLine: { color: "#374151" },
        },
        timeScale: {
          borderColor: "#374151",
          timeVisible: true,
        },
        rightPriceScale: {
          borderColor: "#374151",
        },
      });

      const series = chart.addCandlestickSeries({
        upColor: "#4ade80",
        downColor: "#ef4444",
        borderUpColor: "#4ade80",
        borderDownColor: "#ef4444",
        wickUpColor: "#4ade80",
        wickDownColor: "#ef4444",
      });

      chartApiRef.current = chart;
      seriesRef.current = series;
    }

    // Generate sample candlestick data
    const now = Math.floor(Date.now() / 1000);
    const DAY = 86400;
    const data: CandlestickData[] = [];
    let price = symbol.includes("BTC") ? 65000 : symbol.includes("ETH") ? 3400 : 180;

    for (let i = 60; i >= 1; i--) {
      const change = price * (Math.random() - 0.48) * 0.02;
      const open = price;
      const close = price + change;
      const high = Math.max(open, close) + Math.abs(change) * 0.5;
      const low = Math.min(open, close) - Math.abs(change) * 0.5;
      data.push({
        time: (now - i * DAY) as CandlestickData["time"],
        open,
        high,
        low,
        close,
      });
      price = close;
    }

    seriesRef.current?.setData(data);

    const handleResize = () => {
      if (chartRef.current) {
        chartApiRef.current?.applyOptions({ width: chartRef.current.clientWidth });
      }
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, [symbol]);

  useEffect(() => {
    return () => {
      chartApiRef.current?.remove();
      chartApiRef.current = null;
    };
  }, []);

  const ma = analysis?.market_analyst;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-xl font-semibold text-[oklch(0.92_0_0)]">
            Markets
          </h1>
          <p className="font-mono text-xs text-[oklch(0.6_0_0)]">
            Market Analysis & Price Data
          </p>
        </div>
        <button
          onClick={runAnalysis}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-md bg-[oklch(0.62_0.19_145)] px-3 py-1.5 font-mono text-xs font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          <TrendingUp size={12} />
          {loading ? "Analyzing..." : "Analyze"}
        </button>
      </div>

      {/* Symbol Selector */}
      <div className="flex flex-wrap gap-2">
        {SYMBOLS.map((sym) => (
          <button
            key={sym}
            onClick={() => setSymbol(sym)}
            className={`rounded-md px-3 py-1.5 font-mono text-xs transition-colors ${
              symbol === sym
                ? "bg-[oklch(0.62_0.19_145)] text-black font-medium"
                : "border border-[oklch(0.25_0_0)] text-[oklch(0.6_0_0)] hover:border-[oklch(0.62_0.19_145)] hover:text-[oklch(0.92_0_0)]"
            }`}
          >
            {sym}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-[oklch(0.25_0.08_30)] bg-[oklch(0.25_0.08_30)] px-4 py-2">
          <p className="font-mono text-xs text-[oklch(0.55_0.22_30)]">{error}</p>
        </div>
      )}

      {/* Price Chart */}
      <div className="rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.13_0_0)] p-4">
        <p className="mb-3 font-mono text-xs font-medium text-[oklch(0.6_0_0)] uppercase tracking-wider">
          {symbol} — Price Chart
        </p>
        <div ref={chartRef} className="w-full" />
      </div>

      {/* Analysis Output */}
      {ma ? (
        <div className="rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.18_0.01_145)] p-4">
          <p className="mb-3 font-mono text-xs font-medium text-[oklch(0.6_0_0)] uppercase tracking-wider">
            Market Analysis
          </p>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div>
              <p className="font-mono text-xs text-[oklch(0.6_0_0)]">Direction</p>
              <p
                className={`font-mono text-lg font-semibold ${
                  ma.direction === "long"
                    ? "text-[oklch(0.62_0.19_145)]"
                    : ma.direction === "short"
                      ? "text-[oklch(0.55_0.22_30)]"
                      : "text-[oklch(0.6_0_0)]"
                }`}
              >
                {ma.direction.toUpperCase()}
              </p>
            </div>
            <div>
              <p className="font-mono text-xs text-[oklch(0.6_0_0)]">Confidence</p>
              <p className="font-mono text-lg font-semibold text-[oklch(0.92_0_0)]">
                {ma.confidence.toFixed(1)}%
              </p>
            </div>
            <div>
              <p className="font-mono text-xs text-[oklch(0.6_0_0)]">Indicators</p>
              <div className="flex flex-wrap gap-1.5 mt-1">
                {Object.entries(ma.indicators).map(([key, val]) => (
                  <span
                    key={key}
                    className="rounded bg-[oklch(0.2_0_0)] px-2 py-0.5 font-mono text-xs text-[oklch(0.6_0_0)]"
                  >
                    {key.toUpperCase()}: {typeof val === "number" ? val.toFixed(2) : val}
                  </span>
                ))}
              </div>
            </div>
          </div>
          <p className="mt-3 font-mono text-xs text-[oklch(0.5_0_0)] leading-relaxed">
            {ma.rationale}
          </p>
        </div>
      ) : loading ? (
        <div className="flex items-center justify-center py-8">
          <RefreshCw size={16} className="animate-spin text-[oklch(0.6_0_0)]" />
        </div>
      ) : null}
    </div>
  );
}
