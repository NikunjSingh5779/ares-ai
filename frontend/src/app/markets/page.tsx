"use client";

import { useEffect, useRef, useState } from "react";
import { RefreshCw, TrendingUp, AlertTriangle } from "lucide-react";
import type { IChartApi, ISeriesApi, CandlestickData } from "lightweight-charts";
import { usePipelinePolling } from "@/lib/usePipelinePolling";

const SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "AAPL", "TSLA", "MSFT"];

export default function MarketsPage() {
  const [symbol, setSymbol] = useState("BTC-USD");
  const chartRef = useRef<HTMLDivElement>(null);
  const chartApiRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);

  // Pipeline hook owns the full lifecycle internally.
  const { status: analysis, running, error, timedOut, runAnalysis } = usePipelinePolling();
  const loading = running;

  async function runAnalysisForSymbol() {
    if (running) return;
    await runAnalysis(symbol, "Analyze market");
  }

  // Trigger analysis on mount and whenever the selected symbol changes.
  useEffect(() => {
    runAnalysisForSymbol();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  // Generate dummy price chart data for visualization
  useEffect(() => {
    if (!chartRef.current) return;

    if (!chartApiRef.current) {
      import("lightweight-charts").then(({ createChart, ColorType }) => {
        if (!chartRef.current) return;
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
          timeScale: {
            borderColor: "rgba(255,255,255,0.08)",
            timeVisible: false,
          },
          rightPriceScale: {
            borderColor: "rgba(255,255,255,0.08)",
          },
          crosshair: {
            vertLine: { labelBackgroundColor: "#6366f1" },
            horzLine: { labelBackgroundColor: "#6366f1" },
          },
          width: chartRef.current.clientWidth,
          height: 400,
        });

        chartApiRef.current = chart;
        const series = chart.addCandlestickSeries({
          upColor: "#22c55e",
          downColor: "#ef4444",
          borderUpColor: "#22c55e",
          borderDownColor: "#ef4444",
          wickUpColor: "#22c55e",
          wickDownColor: "#ef4444",
        });
        seriesRef.current = series;

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

        series.setData(data);
        chart.timeScale().fitContent();
      });
    } else if (seriesRef.current) {
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

      seriesRef.current.setData(data);
      chartApiRef.current?.timeScale().fitContent();
    }

    const handleResize = () => {
      if (chartApiRef.current && chartRef.current) {
        chartApiRef.current.resize(chartRef.current.clientWidth, 400);
      }
    };
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [symbol]);

  const hasAnalysis = analysis?.pipeline_status?.completed_nodes?.length;
  const ma = analysis?.market_analyst;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">
            Market Analysis
          </h1>
          <p className="text-label mt-1">
            Real-time price data and technical analysis for major symbols
          </p>
        </div>
        <div className="flex items-center gap-3">
          <select
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-2 font-mono text-xs text-white outline-none focus:border-[#6366f1]"
          >
            {SYMBOLS.map((s) => (
              <option key={s} value={s} className="bg-[#1a1a1a]">
                {s}
              </option>
            ))}
          </select>
          <button
            onClick={runAnalysisForSymbol}
            disabled={running}
            className="btn-primary !py-2 !px-3 !text-xs !font-mono disabled:opacity-50"
          >
            <TrendingUp size={12} />
            {loading ? "Analyzing..." : "Analyze"}
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
            Pipeline timed out after 60 seconds.
          </span>
        </div>
      )}

      {/* Price Chart */}
      <div ref={chartRef} className="w-full rounded-xl overflow-hidden" />

      {/* Analysis Results */}
      {hasAnalysis && !loading ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="card-glass">
            <p className="text-label mb-3">Market Direction</p>
            <p className="font-mono text-2xl font-bold text-white capitalize">
              {ma?.direction ?? "—"}
            </p>
            {ma?.bias && (
              <p className="mt-1 font-mono text-xs text-[#71717a] capitalize">
                Bias: {ma.bias}
              </p>
            )}
          </div>

          <div className="card-glass">
            <p className="text-label mb-3">Confidence</p>
            <p className="font-mono text-3xl font-bold text-[#6366f1]">
              {analysis?.consensus?.composite_confidence ?? ma?.confidence ?? "—"}%
            </p>
            {ma?.indicators && (
              <div className="mt-2 flex flex-wrap gap-2">
                {Object.entries(ma.indicators).slice(0, 5).map(([k, v]) => (
                  <span
                    key={k}
                    className="rounded-md bg-[rgba(99,102,241,0.1)] px-2 py-0.5 font-mono text-[10px] text-[#818cf8]"
                  >
                    {k.toUpperCase()}={typeof v === "number" ? v.toFixed(1) : String(v)}
                  </span>
                ))}
              </div>
            )}
          </div>

          <div className="card-glass">
            <p className="text-label mb-3">Setup</p>
            <p className="font-mono text-sm text-white">
              {ma?.setup ?? "—"}
            </p>
          </div>

          <div className="card-glass">
            <p className="text-label mb-3">Key Levels</p>
            <div className="space-y-1">
              {ma?.entry_zone && (
                <div className="flex justify-between font-mono text-xs">
                  <span className="text-[#a1a1aa]">Entry Zone</span>
                  <span className="text-[#22c55e]">{ma.entry_zone}</span>
                </div>
              )}
              {ma?.stop_loss && (
                <div className="flex justify-between font-mono text-xs">
                  <span className="text-[#a1a1aa]">Stop Loss</span>
                  <span className="text-[#ef4444]">{ma.stop_loss}</span>
                </div>
              )}
              {ma?.targets?.map((t: string, i: number) => (
                <div key={i} className="flex justify-between font-mono text-xs">
                  <span className="text-[#a1a1aa]">Target {i + 1}</span>
                  <span className="text-[#6366f1]">{t}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      ) : loading ? (
        <div className="flex items-center justify-center py-8">
          <RefreshCw size={16} className="animate-spin text-[#6366f1]" />
        </div>
      ) : null}
    </div>
  );
}
