"use client";

import { useEffect, useRef, useState } from "react";
import { RefreshCw, TrendingUp } from "lucide-react";
import { createChart, type IChartApi, type ISeriesApi, type CandlestickData, ColorType } from "lightweight-charts";
import { analyze, getAgentStatus } from "@/lib/api";
import type { AgentStatusResponse } from "@/types/api";

const SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "AAPL", "TSLA", "MSFT"];

export default function MarketsPage() {
  const [symbol, setSymbol] = useState("BTC-USD");
  const [analysis, setAnalysis] = useState<AgentStatusResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const chartRef = useRef<HTMLDivElement>(null);
  const chartApiRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  async function runAnalysis() {
    setLoading(true);
    setError(null);
    try {
      await analyze(symbol);
      const s = await getAgentStatus();
      setAnalysis(s);
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
          textColor: "#52525b",
          fontFamily: "JetBrains Mono, monospace",
        },
        grid: {
          vertLines: { color: "rgba(255,255,255,0.04)" },
          horzLines: { color: "rgba(255,255,255,0.04)" },
        },
        width: chartRef.current.clientWidth,
        height: 400,
        crosshair: {
          vertLine: { color: "rgba(99,102,241,0.3)", labelBackgroundColor: "#6366f1" },
          horzLine: { color: "rgba(99,102,241,0.3)", labelBackgroundColor: "#6366f1" },
        },
        timeScale: {
          borderColor: "rgba(255,255,255,0.08)",
          timeVisible: true,
        },
        rightPriceScale: {
          borderColor: "rgba(255,255,255,0.08)",
        },
      });

      const series = chart.addCandlestickSeries({
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderUpColor: "#22c55e",
        borderDownColor: "#ef4444",
        wickUpColor: "#22c55e",
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
          <h1 className="text-heading text-xl text-white">
            Markets
          </h1>
          <p className="text-label mt-1">
            Market Analysis & Price Data
          </p>
        </div>
        <button
          onClick={runAnalysis}
          disabled={loading}
          className="btn-primary !py-2 !px-3 !text-xs !font-mono disabled:opacity-50"
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
            className={`rounded-lg px-3 py-1.5 font-mono text-xs transition-all duration-200 ${
              symbol === sym
                ? "bg-[#6366f1] text-black font-semibold shadow-lg shadow-[rgba(99,102,241,0.25)]"
                : "border border-[rgba(255,255,255,0.08)] text-[#a1a1aa] hover:border-[#6366f1] hover:text-white"
            }`}
          >
            {sym}
          </button>
        ))}
      </div>

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3">
          <p className="font-mono text-xs text-[#ef4444]">{error}</p>
        </div>
      )}

      {/* Price Chart */}
      <div className="card-glass !p-0 overflow-hidden">
        <div className="px-6 pt-5 pb-3">
          <p className="text-label">
            {symbol} — Price Chart
          </p>
        </div>
        <div ref={chartRef} className="w-full px-2 pb-2" />
      </div>

      {/* Analysis Output */}
      {ma ? (
        <div className="card-glass">
          <p className="text-label mb-4">
            Market Analysis
          </p>
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-3">
            <div>
              <p className="text-label">Direction</p>
              <p
                className={`font-sans text-xl font-bold mt-1 ${
                  ma.direction === "long"
                    ? "text-[#22c55e]"
                    : ma.direction === "short"
                      ? "text-[#ef4444]"
                      : "text-[#a1a1aa]"
                }`}
              >
                {ma.direction.toUpperCase()}
              </p>
            </div>
            <div>
              <p className="text-label">Confidence</p>
              <p className="font-sans text-xl font-bold text-white mt-1">
                {ma.confidence.toFixed(1)}%
              </p>
            </div>
            <div>
              <p className="text-label">Indicators</p>
              <div className="flex flex-wrap gap-1.5 mt-2">
                {Object.entries(ma.indicators).map(([key, val]) => (
                  <span
                    key={key}
                    className="rounded-lg bg-[rgba(255,255,255,0.04)] border border-[rgba(255,255,255,0.08)] px-2 py-1 font-mono text-xs text-[#a1a1aa]"
                  >
                    {key.toUpperCase()}: {typeof val === "number" ? val.toFixed(2) : val}
                  </span>
                ))}
              </div>
            </div>
          </div>
          <p className="mt-4 font-mono text-xs text-[#71717a] leading-relaxed border-t border-[rgba(255,255,255,0.06)] pt-3">
            {ma.rationale}
          </p>
        </div>
      ) : loading ? (
        <div className="flex items-center justify-center py-8">
          <RefreshCw size={16} className="animate-spin text-[#6366f1]" />
        </div>
      ) : null}
    </div>
  );
}
