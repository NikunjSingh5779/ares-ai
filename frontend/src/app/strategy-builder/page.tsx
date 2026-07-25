"use client";

import { useState } from "react";
import { Save, Play, RefreshCw, FlaskConical } from "lucide-react";

const STRATEGY_TEMPLATES = [
  { id: "momentum", name: "Momentum", description: "Follow price trends with moving average crossovers" },
  { id: "mean_reversion", name: "Mean Reversion", description: "Trade pullbacks using RSI and Bollinger Bands" },
  { id: "grid_trading", name: "Grid Trading", description: "Place buy/sell orders at predefined price intervals" },
  { id: "dca", name: "DCA", description: "Dollar-cost average into positions at regular intervals" },
  { id: "custom", name: "Custom", description: "Define your own strategy parameters" },
];

const INDICATOR_OPTIONS = [
  { id: "sma", name: "SMA", periods: [10, 20, 50, 100, 200] },
  { id: "ema", name: "EMA", periods: [9, 12, 21, 26, 50] },
  { id: "rsi", name: "RSI", periods: [14, 21] },
  { id: "macd", name: "MACD", default: "12,26,9" },
  { id: "bb", name: "Bollinger Bands", periods: [20] },
];

export default function StrategyBuilderPage() {
  const [name, setName] = useState("");
  const [selectedTemplate, setSelectedTemplate] = useState("momentum");
  const [selectedIndicators, setSelectedIndicators] = useState<string[]>(["sma", "rsi"]);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const toggleIndicator = (id: string) => {
    setSelectedIndicators((prev) =>
      prev.includes(id) ? prev.filter((i) => i !== id) : [...prev, id],
    );
  };

  const handleSave = async () => {
    setSaving(true);
    // Simulate saving — no dedicated endpoint yet
    await new Promise((r) => setTimeout(r, 800));
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">Strategy Builder</h1>
          <p className="text-label mt-1">Create & Configure Trading Strategies</p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleSave}
            disabled={saving || !name}
            className="btn-primary !py-2 !px-3 !text-xs !font-mono disabled:opacity-50"
          >
            <Save size={12} />
            {saving ? "Saving..." : saved ? "Saved!" : "Save Strategy"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* Configuration Panel */}
        <div className="lg:col-span-2 space-y-6">
          {/* Strategy Name */}
          <div className="card-glass">
            <p className="text-label mb-3">Strategy Name</p>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="e.g., Momentum v2"
              className="w-full rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-4 py-2.5 font-mono text-sm text-white placeholder-[#52525b] outline-none transition-colors focus:border-[#6366f1]"
            />
          </div>

          {/* Indicator Selection */}
          <div className="card-glass">
            <p className="text-label mb-3">Indicators</p>
            <div className="flex flex-wrap gap-2">
              {INDICATOR_OPTIONS.map((ind) => (
                <button
                  key={ind.id}
                  onClick={() => toggleIndicator(ind.id)}
                  className={`rounded-lg px-3 py-1.5 font-mono text-xs transition-all ${
                    selectedIndicators.includes(ind.id)
                      ? "bg-[#6366f1] text-black font-semibold shadow-lg shadow-[rgba(99,102,241,0.25)]"
                      : "border border-[rgba(255,255,255,0.08)] text-[#a1a1aa] hover:border-[#6366f1] hover:text-white"
                  }`}
                >
                  {ind.name}
                </button>
              ))}
            </div>
            {selectedIndicators.length > 0 && (
              <div className="mt-4 space-y-2 border-t border-[rgba(255,255,255,0.06)] pt-4">
                <p className="text-label text-[10px]">Selected Configuration</p>
                {selectedIndicators.map((id) => {
                  const ind = INDICATOR_OPTIONS.find((i) => i.id === id);
                  return (
                    <div key={id} className="flex items-center justify-between rounded-lg bg-[rgba(255,255,255,0.03)] px-3 py-2">
                      <span className="font-mono text-xs text-white">{ind?.name}</span>
                      <span className="font-mono text-[10px] text-[#52525b]">
                        {ind?.periods?.join(", ") || ind?.default || "default"}
                      </span>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          {/* Parameters */}
          <div className="card-glass">
            <p className="text-label mb-3">Parameters</p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              <div>
                <label className="font-mono text-[10px] text-[#52525b] uppercase tracking-wider">Position Size</label>
                <input
                  type="number"
                  defaultValue={10}
                  className="mt-1.5 w-full rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-2 font-mono text-xs text-white outline-none focus:border-[#6366f1]"
                  placeholder="%"
                />
              </div>
              <div>
                <label className="font-mono text-[10px] text-[#52525b] uppercase tracking-wider">Stop Loss</label>
                <input
                  type="number"
                  defaultValue={5}
                  className="mt-1.5 w-full rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-2 font-mono text-xs text-white outline-none focus:border-[#6366f1]"
                  placeholder="%"
                />
              </div>
              <div>
                <label className="font-mono text-[10px] text-[#52525b] uppercase tracking-wider">Take Profit</label>
                <input
                  type="number"
                  defaultValue={15}
                  className="mt-1.5 w-full rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-2 font-mono text-xs text-white outline-none focus:border-[#6366f1]"
                  placeholder="%"
                />
              </div>
            </div>
          </div>
        </div>

        {/* Sidebar */}
        <div className="space-y-6">
          {/* Templates */}
          <div className="card-glass">
            <p className="text-label mb-3">Templates</p>
            <div className="space-y-2">
              {STRATEGY_TEMPLATES.map((tpl) => (
                <button
                  key={tpl.id}
                  onClick={() => setSelectedTemplate(tpl.id)}
                  className={`w-full rounded-lg border px-3 py-2.5 text-left transition-all ${
                    selectedTemplate === tpl.id
                      ? "border-[#6366f1] bg-[rgba(99,102,241,0.08)]"
                      : "border-[rgba(255,255,255,0.06)] hover:border-[rgba(255,255,255,0.12)]"
                  }`}
                >
                  <p className="font-sans text-sm font-medium text-white">{tpl.name}</p>
                  <p className="font-mono text-[10px] text-[#52525b] mt-0.5">{tpl.description}</p>
                </button>
              ))}
            </div>
          </div>

          {/* Quick Actions */}
          <div className="card-glass">
            <p className="text-label mb-3">Actions</p>
            <div className="space-y-2">
              <button className="flex w-full items-center gap-2 rounded-lg border border-[rgba(255,255,255,0.08)] px-3 py-2.5 text-left font-mono text-xs text-[#a1a1aa] transition-colors hover:border-[#6366f1] hover:text-white">
                <Play size={12} />
                Backtest Strategy
              </button>
              <button className="flex w-full items-center gap-2 rounded-lg border border-[rgba(255,255,255,0.08)] px-3 py-2.5 text-left font-mono text-xs text-[#a1a1aa] transition-colors hover:border-[#22c55e] hover:text-white">
                <FlaskConical size={12} />
                Paper Trade
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
