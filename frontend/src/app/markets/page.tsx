"use client";

import { useEffect, useRef, useState } from "react";
import { AlertTriangle, RefreshCw, TrendingUp } from "lucide-react";
import type { CandlestickData, IChartApi, ISeriesApi, UTCTimestamp } from "lightweight-charts";
import { getCandles, getSettings } from "@/lib/api";
import { usePipelinePolling } from "@/lib/usePipelinePolling";

const SYMBOLS = ["BTC-USD", "ETH-USD", "SOL-USD", "AAPL", "TSLA", "MSFT"];
const DEFAULT_INTERVAL = "1d";
const CANDLE_LIMIT = 120;
const CHART_HEIGHT = 400;

export default function MarketsPage() {
  const [symbol, setSymbol] = useState("BTC-USD");
  const [preferencesReady, setPreferencesReady] = useState(false);
  const [candles, setCandles] = useState<CandlestickData[]>([]);
  const [chartReady, setChartReady] = useState(false);
  const [chartLoading, setChartLoading] = useState(true);
  const [chartError, setChartError] = useState<string | null>(null);

  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const seriesRef = useRef<ISeriesApi<"Candlestick"> | null>(null);
  const analysisInFlightRef = useRef(false);

  const { status: analysis, running, error, timedOut, runAnalysis } = usePipelinePolling();
  const analysisSymbol = analysis?.symbol;
  const hasAnalysis = Boolean(analysis?.pipeline_status?.completed_nodes?.length);
  const ma = analysis?.market_analyst;
  const confidence = analysis?.consensus?.composite_confidence ?? ma?.confidence;

  // Create the chart once and dispose it on unmount.
  useEffect(() => {
    let disposed = false;
    let chart: IChartApi | null = null;
    let observer: ResizeObserver | null = null;

    void import("lightweight-charts").then(({ CandlestickSeries, ColorType, createChart }) => {
      const container = chartContainerRef.current;
      if (disposed || !container) return;

      chart = createChart(container, {
        layout: {
          background: { type: ColorType.Solid, color: "transparent" },
          textColor: "#a1a1aa",
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
        width: container.clientWidth,
        height: CHART_HEIGHT,
      });

      seriesRef.current = chart.addSeries(CandlestickSeries, {
        upColor: "#22c55e",
        downColor: "#ef4444",
        borderUpColor: "#22c55e",
        borderDownColor: "#ef4444",
        wickUpColor: "#22c55e",
        wickDownColor: "#ef4444",
      });
      chartRef.current = chart;

      observer = new ResizeObserver(() => {
        if (chart && container.clientWidth > 0) {
          chart.applyOptions({ width: container.clientWidth });
        }
      });
      observer.observe(container);

      if (!disposed) setChartReady(true);
    });

    return () => {
      disposed = true;
      observer?.disconnect();
      seriesRef.current = null;
      chartRef.current = null;
      chart?.remove();
    };
  }, []);

  // Apply the saved default symbol before the first candle request. If the
  // settings store is unavailable, fall back to the built-in default.
  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;

    getSettings(controller.signal)
      .then((settings) => {
        if (!cancelled) setSymbol(settings.preferences.default_symbol);
      })
      .catch(() => {})
      .finally(() => {
        if (!cancelled) setPreferencesReady(true);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  // Load real candles whenever the selected symbol changes. Analysis is not
  // triggered here: it is an explicit operator action.
  useEffect(() => {
    if (!preferencesReady) return;

    const controller = new AbortController();
    let cancelled = false;

    setCandles([]);
    setChartError(null);
    setChartLoading(true);

    getCandles(symbol, DEFAULT_INTERVAL, CANDLE_LIMIT, controller.signal)
      .then((response) => {
        if (cancelled) return;
        setCandles(
          response.candles.map((candle) => ({
            time: candle.time as UTCTimestamp,
            open: candle.open,
            high: candle.high,
            low: candle.low,
            close: candle.close,
          })),
        );
      })
      .catch((err: unknown) => {
        if (cancelled || controller.signal.aborted) return;
        setChartError(err instanceof Error ? err.message : `Failed to load candles for ${symbol}`);
      })
      .finally(() => {
        if (!cancelled) setChartLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [symbol, preferencesReady]);

  // Push fetched data into the chart once both are ready.
  useEffect(() => {
    if (!chartReady || !seriesRef.current) return;
    seriesRef.current.setData(candles);
    chartRef.current?.timeScale().fitContent();
  }, [candles, chartReady]);

  async function runAnalysisForSymbol() {
    if (analysisInFlightRef.current) return;
    analysisInFlightRef.current = true;
    try {
      await runAnalysis(symbol, "Analyze market");
    } finally {
      analysisInFlightRef.current = false;
    }
  }

  // Keep a saved preference visible even when it is outside the preset list.
  const symbolOptions = SYMBOLS.includes(symbol) ? SYMBOLS : [symbol, ...SYMBOLS];

  return (
    <div className="space-y-6">
      <p className="sr-only" role="status" aria-live="polite">
        {running
          ? `Analysis running for ${symbol}`
          : error
            ? `Analysis failed: ${error}`
            : hasAnalysis && analysisSymbol
              ? `Analysis complete for ${analysisSymbol}`
              : ""}
      </p>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">Market Analysis</h1>
          <p className="text-label mt-1">
            Real price data and technical analysis for major symbols
          </p>
        </div>
        <div className="flex items-center gap-3">
          <label htmlFor="market-symbol" className="sr-only">
            Symbol
          </label>
          <select
            id="market-symbol"
            value={symbol}
            onChange={(e) => setSymbol(e.target.value)}
            className="rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-2 font-mono text-xs text-white outline-none focus:border-[#6366f1]"
          >
            {symbolOptions.map((s) => (
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
            {running ? "Analyzing..." : "Analyze"}
          </button>
        </div>
      </div>

      {/* Analysis errors */}
      {error && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3"
        >
          <AlertTriangle size={14} className="text-[#ef4444]" />
          <span className="font-mono text-xs text-[#ef4444]">{error}</span>
        </div>
      )}
      {timedOut && (
        <div
          role="alert"
          className="flex items-center gap-2 rounded-xl border border-[rgba(255,159,28,0.2)] bg-[rgba(255,159,28,0.08)] px-4 py-3"
        >
          <AlertTriangle size={14} className="text-[#ff9f1c]" />
          <span className="font-mono text-xs text-[#ff9f1c]">
            Pipeline timed out after 60 seconds.
          </span>
        </div>
      )}

      {/* Price chart */}
      <div>
        <div className="mb-2 flex items-center justify-between">
          <p className="text-label">
            {DEFAULT_INTERVAL === "1d" ? "Daily" : DEFAULT_INTERVAL} candles · {symbol}
          </p>
          <p className="font-mono text-[10px] text-[#a1a1aa]" aria-live="polite">
            {chartLoading
              ? "Loading market data..."
              : candles.length > 0
                ? `${candles.length} candles`
                : "No data"}
          </p>
        </div>
        <div
          ref={chartContainerRef}
          role="figure"
          aria-label={`Daily candlestick chart for ${symbol}`}
          className="w-full overflow-hidden rounded-xl"
          style={{ height: CHART_HEIGHT }}
        />
        {chartError && !chartLoading && (
          <div
            role="alert"
            className="mt-3 flex items-center gap-2 rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3"
          >
            <AlertTriangle size={14} className="text-[#ef4444]" />
            <span className="font-mono text-xs text-[#ef4444]">
              Market data unavailable: {chartError}
            </span>
          </div>
        )}
        {!chartLoading && !chartError && candles.length === 0 && (
          <p className="mt-3 font-mono text-xs text-[#a1a1aa]">
            No candles were returned for {symbol}.
          </p>
        )}
      </div>

      {/* Analysis results */}
      {hasAnalysis && !running ? (
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <div className="card-glass">
            <p className="text-label mb-3">Market Direction · {analysisSymbol ?? symbol}</p>
            <p className="font-mono text-2xl font-bold text-white capitalize">
              {ma?.direction ?? "—"}
            </p>
            {ma?.bias && (
              <p className="mt-1 font-mono text-xs text-[#a1a1aa] capitalize">
                Bias: {ma.bias}
              </p>
            )}
          </div>

          <div className="card-glass">
            <p className="text-label mb-3">Confidence</p>
            <p className="font-mono text-3xl font-bold text-[#6366f1]">
              {typeof confidence === "number" ? `${confidence}%` : "—"}
            </p>
            {ma?.indicators && (
              <div className="mt-2 flex flex-wrap gap-2">
                {Object.entries(ma.indicators)
                  .slice(0, 5)
                  .map(([k, v]) => (
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
            <p className="font-mono text-sm text-white">{ma?.setup ?? "—"}</p>
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
      ) : running ? (
        <div className="flex items-center justify-center gap-2 py-8" role="status">
          <RefreshCw size={16} className="animate-spin text-[#6366f1]" />
          <span className="font-mono text-xs text-[#a1a1aa]">Running analysis for {symbol}...</span>
        </div>
      ) : null}
    </div>
  );
}
