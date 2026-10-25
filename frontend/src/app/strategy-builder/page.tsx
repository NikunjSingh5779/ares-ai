"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  CheckCircle2,
  FlaskConical,
  Play,
  Plus,
  RefreshCw,
  Save,
} from "lucide-react";
import { createStrategy, listStrategies, updateStrategy } from "@/lib/api";
import type { Strategy, StrategyInput, StrategyType } from "@/types/api";

const STRATEGY_TEMPLATES: Array<{
  id: StrategyType;
  name: string;
  description: string;
}> = [
  { id: "momentum", name: "Momentum", description: "Follow price trends with moving average crossovers" },
  { id: "mean_reversion", name: "Mean Reversion", description: "Trade pullbacks using RSI and Bollinger Bands" },
  { id: "trend_following", name: "Trend Following", description: "Stay with a sustained directional move" },
  { id: "grid", name: "Grid Trading", description: "Place buy/sell orders at predefined price intervals" },
  { id: "dca", name: "DCA", description: "Dollar-cost average into positions at regular intervals" },
  { id: "arbitrage", name: "Arbitrage", description: "Compare related markets for a pricing gap" },
  { id: "ml", name: "ML", description: "Use a model-driven signal set" },
  { id: "custom", name: "Custom", description: "Define your own strategy parameters" },
];

const INDICATOR_OPTIONS = [
  { id: "sma", name: "SMA", periods: [10, 20, 50, 100, 200] },
  { id: "ema", name: "EMA", periods: [9, 12, 21, 26, 50] },
  { id: "rsi", name: "RSI", periods: [14, 21] },
  { id: "macd", name: "MACD", default: "12,26,9" },
  { id: "bb", name: "Bollinger Bands", periods: [20] },
];

const DEFAULT_PARAMETERS = {
  positionSize: "10",
  stopLoss: "5",
  takeProfit: "15",
};

// The backtest engine supports this subset; other draft types can still be saved.
const BACKTEST_STRATEGIES = new Set(["momentum", "mean_reversion", "trend_following", "breakout"]);

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    (error as { name?: unknown }).name === "AbortError"
  );
}

function messageFor(error: unknown, fallback: string): string {
  return error instanceof Error ? error.message : fallback;
}

function prettyType(value: string): string {
  return value.replaceAll("_", " ");
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "unknown" : date.toLocaleString();
}

export default function StrategyBuilderPage() {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedTemplate, setSelectedTemplate] = useState<StrategyType>("momentum");
  const [selectedIndicators, setSelectedIndicators] = useState<string[]>(["sma", "rsi"]);
  const [positionSize, setPositionSize] = useState(DEFAULT_PARAMETERS.positionSize);
  const [stopLoss, setStopLoss] = useState(DEFAULT_PARAMETERS.stopLoss);
  const [takeProfit, setTakeProfit] = useState(DEFAULT_PARAMETERS.takeProfit);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [savedStrategies, setSavedStrategies] = useState<Strategy[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [saving, setSaving] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadSavedStrategies = useCallback(async (signal?: AbortSignal) => {
    setLoadingList(true);
    try {
      const items = await listStrategies(signal);
      if (!signal?.aborted) setSavedStrategies(items);
    } catch (loadError) {
      if (!isAbortError(loadError) && !signal?.aborted) {
        setError(messageFor(loadError, "Failed to load saved strategies"));
      }
    } finally {
      if (!signal?.aborted) setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void loadSavedStrategies(controller.signal);
    return () => controller.abort();
  }, [loadSavedStrategies]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(null), 2500);
    return () => window.clearTimeout(timer);
  }, [notice]);

  const toggleIndicator = (id: string) => {
    setSelectedIndicators((previous) =>
      previous.includes(id) ? previous.filter((item) => item !== id) : [...previous, id],
    );
  };

  const resetForm = () => {
    setSelectedId(null);
    setName("");
    setDescription("");
    setSelectedTemplate("momentum");
    setSelectedIndicators(["sma", "rsi"]);
    setPositionSize(DEFAULT_PARAMETERS.positionSize);
    setStopLoss(DEFAULT_PARAMETERS.stopLoss);
    setTakeProfit(DEFAULT_PARAMETERS.takeProfit);
    setNotice(null);
    setError(null);
  };

  const loadStrategy = (strategy: Strategy) => {
    setSelectedId(strategy.id);
    setName(strategy.name);
    setDescription(strategy.description);
    setSelectedTemplate(strategy.strategy_type);
    setSelectedIndicators(strategy.config.indicators);
    setPositionSize(String(strategy.parameters.position_size_pct));
    setStopLoss(String(strategy.parameters.stop_loss_pct));
    setTakeProfit(String(strategy.parameters.take_profit_pct));
    setNotice(null);
    setError(null);
  };

  const buildPayload = (): StrategyInput | null => {
    const trimmedName = name.trim();
    if (!trimmedName) {
      setError("Give the strategy a name before saving");
      return null;
    }

    const parsed = {
      position_size_pct: Number(positionSize),
      stop_loss_pct: Number(stopLoss),
      take_profit_pct: Number(takeProfit),
    };
    for (const [label, value] of [
      ["Position size", parsed.position_size_pct],
      ["Stop loss", parsed.stop_loss_pct],
      ["Take profit", parsed.take_profit_pct],
    ] as const) {
      if (!Number.isFinite(value) || value <= 0 || value > 100) {
        setError(`${label} must be greater than 0 and at most 100`);
        return null;
      }
    }

    return {
      name: trimmedName,
      description: description.trim(),
      strategy_type: selectedTemplate,
      config: { indicators: selectedIndicators },
      parameters: parsed,
    };
  };

  const handleSave = async () => {
    const payload = buildPayload();
    if (!payload) return;

    setSaving(true);
    setError(null);
    setNotice(null);
    try {
      const result = selectedId
        ? await updateStrategy(selectedId, payload)
        : await createStrategy(payload);
      setSelectedId(result.id);
      setSavedStrategies((previous) => [
        result,
        ...previous.filter((strategy) => strategy.id !== result.id),
      ]);
      setNotice(selectedId ? "Strategy updated" : "Strategy saved as a draft");
    } catch (saveError) {
      setError(messageFor(saveError, "Failed to save the strategy"));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-heading text-xl text-white">Strategy Builder</h1>
          <p className="text-label mt-1">Create & Configure Trading Strategies</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={resetForm}
            className="btn-ghost !px-3 !py-2 !text-xs !font-mono"
          >
            <Plus size={12} />
            New Draft
          </button>
          <button
            type="button"
            onClick={() => void loadSavedStrategies()}
            disabled={loadingList}
            className="btn-ghost !px-3 !py-2 !text-xs !font-mono disabled:opacity-50"
          >
            <RefreshCw size={12} className={loadingList ? "animate-spin" : ""} />
            Refresh
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving || !name.trim()}
            aria-busy={saving}
            className="btn-primary !px-3 !py-2 !text-xs !font-mono disabled:opacity-50"
          >
            <Save size={12} />
            {saving ? "Saving..." : selectedId ? "Update Draft" : "Save Draft"}
          </button>
        </div>
      </div>

      {error && (
        <div
          role="alert"
          className="flex items-start gap-2 rounded-xl border border-[rgba(239,68,68,0.25)] bg-[rgba(239,68,68,0.08)] px-4 py-3"
        >
          <AlertCircle size={16} className="mt-0.5 shrink-0 text-[#ef4444]" aria-hidden="true" />
          <p className="font-mono text-xs text-[#fca5a5]">{error}</p>
        </div>
      )}

      {notice && (
        <p
          role="status"
          aria-live="polite"
          className="flex items-center gap-2 rounded-xl border border-[rgba(34,197,94,0.25)] bg-[rgba(34,197,94,0.08)] px-4 py-3 font-mono text-xs text-[#86efac]"
        >
          <CheckCircle2 size={16} aria-hidden="true" />
          {notice}
        </p>
      )}

      <p className="rounded-xl border border-[rgba(255,255,255,0.06)] px-4 py-3 font-mono text-[11px] leading-relaxed text-[#a1a1aa]">
        Saving a draft never enables live trading. The server keeps status, live
        enablement, and promotion counters read-only; every trade still passes the
        Risk, consensus, paper-promotion, and kill-switch gates.
      </p>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <div className="card-glass">
            <label htmlFor="strategy-name" className="text-label mb-3 block">
              Strategy Name
            </label>
            <input
              id="strategy-name"
              type="text"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={100}
              placeholder="e.g., Momentum v2"
              className="w-full rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-4 py-2.5 font-mono text-sm text-white placeholder-[#8b8b93] outline-none transition-colors focus:border-[#6366f1]"
            />
            <label htmlFor="strategy-description" className="text-label mt-4 mb-2 block">
              Description
            </label>
            <textarea
              id="strategy-description"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              maxLength={2000}
              rows={3}
              placeholder="What edge does this draft try to capture?"
              className="w-full resize-y rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-4 py-2.5 font-mono text-sm text-white placeholder-[#8b8b93] outline-none transition-colors focus:border-[#6366f1]"
            />
          </div>

          <div className="card-glass">
            <p className="text-label mb-3">Indicators</p>
            <div className="flex flex-wrap gap-2">
              {INDICATOR_OPTIONS.map((indicator) => (
                <button
                  key={indicator.id}
                  type="button"
                  aria-pressed={selectedIndicators.includes(indicator.id)}
                  onClick={() => toggleIndicator(indicator.id)}
                  className={`rounded-lg px-3 py-1.5 font-mono text-xs transition-all ${
                    selectedIndicators.includes(indicator.id)
                      ? "bg-[#6366f1] text-black font-semibold shadow-lg shadow-[rgba(99,102,241,0.25)]"
                      : "border border-[rgba(255,255,255,0.08)] text-[#a1a1aa] hover:border-[#6366f1] hover:text-white"
                  }`}
                >
                  {indicator.name}
                </button>
              ))}
            </div>
            {selectedIndicators.length > 0 && (
              <div className="mt-4 space-y-2 border-t border-[rgba(255,255,255,0.06)] pt-4">
                <p className="text-label text-[10px]">Selected Configuration</p>
                {selectedIndicators.map((id) => {
                  const indicator = INDICATOR_OPTIONS.find((item) => item.id === id);
                  return (
                    <div
                      key={id}
                      className="flex items-center justify-between rounded-lg bg-[rgba(255,255,255,0.03)] px-3 py-2"
                    >
                      <span className="font-mono text-xs text-white">{indicator?.name ?? id}</span>
                      <span className="font-mono text-[10px] text-[#8b8b93]">
                        {indicator?.periods?.join(", ") || indicator?.default || "default"}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div className="card-glass">
            <p className="text-label mb-3">Parameters</p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div>
                <label
                  htmlFor="position-size"
                  className="font-mono text-[10px] text-[#8b8b93] uppercase tracking-wider"
                >
                  Position Size (%)
                </label>
                <input
                  id="position-size"
                  type="number"
                  inputMode="decimal"
                  min="0.01"
                  max="100"
                  step="0.01"
                  value={positionSize}
                  onChange={(event) => setPositionSize(event.target.value)}
                  className="mt-1.5 w-full rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-2 font-mono text-xs text-white outline-none focus:border-[#6366f1]"
                />
              </div>
              <div>
                <label
                  htmlFor="stop-loss"
                  className="font-mono text-[10px] text-[#8b8b93] uppercase tracking-wider"
                >
                  Stop Loss (%)
                </label>
                <input
                  id="stop-loss"
                  type="number"
                  inputMode="decimal"
                  min="0.01"
                  max="100"
                  step="0.01"
                  value={stopLoss}
                  onChange={(event) => setStopLoss(event.target.value)}
                  className="mt-1.5 w-full rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-2 font-mono text-xs text-white outline-none focus:border-[#6366f1]"
                />
              </div>
              <div>
                <label
                  htmlFor="take-profit"
                  className="font-mono text-[10px] text-[#8b8b93] uppercase tracking-wider"
                >
                  Take Profit (%)
                </label>
                <input
                  id="take-profit"
                  type="number"
                  inputMode="decimal"
                  min="0.01"
                  max="100"
                  step="0.01"
                  value={takeProfit}
                  onChange={(event) => setTakeProfit(event.target.value)}
                  className="mt-1.5 w-full rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-2 font-mono text-xs text-white outline-none focus:border-[#6366f1]"
                />
              </div>
            </div>
            <p className="mt-3 font-mono text-[10px] leading-relaxed text-[#8b8b93]">
              Draft parameters are inputs to the strategy, not safety limits. The live
              position cap and risk ceiling remain enforced by the backend.
            </p>
          </div>
        </div>

        <div className="space-y-6">
          <div className="card-glass">
            <p className="text-label mb-3">Templates</p>
            <div className="space-y-2">
              {STRATEGY_TEMPLATES.map((template) => (
                <button
                  key={template.id}
                  type="button"
                  aria-pressed={selectedTemplate === template.id}
                  onClick={() => setSelectedTemplate(template.id)}
                  className={`w-full rounded-lg border px-3 py-2.5 text-left transition-all ${
                    selectedTemplate === template.id
                      ? "border-[#6366f1] bg-[rgba(99,102,241,0.08)]"
                      : "border-[rgba(255,255,255,0.06)] hover:border-[rgba(255,255,255,0.12)]"
                  }`}
                >
                  <p className="font-sans text-sm font-medium text-white">{template.name}</p>
                  <p className="mt-0.5 font-mono text-[10px] text-[#8b8b93]">
                    {template.description}
                  </p>
                </button>
              ))}
            </div>
          </div>

          <div className="card-glass">
            <div className="mb-3 flex items-center justify-between gap-2">
              <p className="text-label">Saved Drafts</p>
              {loadingList && <span className="font-mono text-[10px] text-[#8b8b93]">loading</span>}
            </div>
            {!loadingList && savedStrategies.length === 0 && (
              <p className="font-mono text-[11px] leading-relaxed text-[#8b8b93]">
                No saved strategies yet. Name a draft and save it to persist it.
              </p>
            )}
            <div className="space-y-2">
              {savedStrategies.map((strategy) => (
                <button
                  key={strategy.id}
                  type="button"
                  aria-pressed={selectedId === strategy.id}
                  onClick={() => loadStrategy(strategy)}
                  className={`w-full rounded-lg border px-3 py-2.5 text-left transition-all ${
                    selectedId === strategy.id
                      ? "border-[#22c55e] bg-[rgba(34,197,94,0.08)]"
                      : "border-[rgba(255,255,255,0.06)] hover:border-[rgba(255,255,255,0.12)]"
                  }`}
                >
                  <div className="flex items-center justify-between gap-2">
                    <p className="font-sans text-sm font-medium text-white">{strategy.name}</p>
                    <span className="rounded-md bg-[rgba(255,255,255,0.06)] px-1.5 py-0.5 font-mono text-[9px] uppercase tracking-wide text-[#a1a1aa]">
                      {strategy.status}
                    </span>
                  </div>
                  <p className="mt-0.5 font-mono text-[10px] text-[#8b8b93]">
                    {prettyType(strategy.strategy_type)} · v{strategy.version} ·{" "}
                    {formatDate(strategy.updated_at)}
                  </p>
                </button>
              ))}
            </div>
          </div>

          <div className="card-glass">
            <p className="text-label mb-3">Actions</p>
            <div className="space-y-2">
              {BACKTEST_STRATEGIES.has(selectedTemplate) ? (
                <Link
                  href={`/backtests?strategy=${encodeURIComponent(selectedTemplate)}`}
                  className="flex w-full items-center gap-2 rounded-lg border border-[rgba(255,255,255,0.08)] px-3 py-2.5 text-left font-mono text-xs text-[#a1a1aa] transition-colors hover:border-[#6366f1] hover:text-white"
                >
                  <Play size={12} />
                  Backtest This Type
                </Link>
              ) : (
                <span className="flex w-full cursor-not-allowed items-center gap-2 rounded-lg border border-[rgba(255,255,255,0.04)] px-3 py-2.5 font-mono text-xs text-[#8b8b93]">
                  <Play size={12} />
                  Backtest not available for this type yet
                </span>
              )}
              <Link
                href="/paper-trading"
                className="flex w-full items-center gap-2 rounded-lg border border-[rgba(255,255,255,0.08)] px-3 py-2.5 text-left font-mono text-xs text-[#a1a1aa] transition-colors hover:border-[#22c55e] hover:text-white"
              >
                <FlaskConical size={12} />
                Paper Trading Dashboard
              </Link>
            </div>
            <p className="mt-3 font-mono text-[10px] leading-relaxed text-[#8b8b93]">
              Promoting a draft to paper or live trading is a separate gated process.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
