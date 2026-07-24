"use client";

import { useState } from "react";
import { Save, RefreshCw, Eye, EyeOff } from "lucide-react";

type TradingMode = "human_approval" | "semi" | "auto";

interface SettingGroup {
  title: string;
  settings: { key: string; label: string; type: "text" | "number" | "select" | "toggle"; value: string | number | boolean; options?: { label: string; value: string }[] }[];
}

const DEFAULT_SETTINGS: SettingGroup[] = [
  {
    title: "Trading",
    settings: [
      { key: "default_mode", label: "Default Trading Mode", type: "select", value: "human_approval", options: [
        { label: "Human Approval", value: "human_approval" },
        { label: "Semi-Autonomous", value: "semi" },
        { label: "Full Autonomous", value: "auto" },
      ]},
      { key: "max_position_size", label: "Max Position Size (%)", type: "number", value: 10 },
      { key: "daily_loss_limit", label: "Daily Loss Limit (%)", type: "number", value: 5 },
      { key: "auto_hedge", label: "Auto-Hedge Enabled", type: "toggle", value: false },
    ],
  },
  {
    title: "Risk",
    settings: [
      { key: "max_drawdown", label: "Max Drawdown (%)", type: "number", value: 15 },
      { key: "min_confidence", label: "Min Consensus Confidence (%)", type: "number", value: 80 },
      { key: "stop_loss_default", label: "Default Stop Loss (%)", type: "number", value: 5 },
      { key: "take_profit_default", label: "Default Take Profit (%)", type: "number", value: 15 },
    ],
  },
  {
    title: "Notifications",
    settings: [
      { key: "email_alerts", label: "Email Alerts", type: "toggle", value: false },
      { key: "trade_confirmations", label: "Trade Confirmations", type: "toggle", value: true },
      { key: "error_reports", label: "Error Reports", type: "toggle", value: true },
    ],
  },
  {
    title: "Display",
    settings: [
      { key: "refresh_interval", label: "Auto-Refresh Interval (s)", type: "number", value: 30 },
      { key: "price_format", label: "Price Format", type: "select", value: "usd", options: [
        { label: "USD ($)", value: "usd" },
        { label: "USDT", value: "usdt" },
        { label: "BTC", value: "btc" },
      ]},
      { key: "show_meme_mode", label: "Show Meme Mode", type: "toggle", value: false },
    ],
  },
];

export default function SettingsPage() {
  const [groups, setGroups] = useState(DEFAULT_SETTINGS);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [showSecrets, setShowSecrets] = useState(false);

  const updateSetting = (groupIdx: number, key: string, value: string | number | boolean) => {
    setGroups((prev) =>
      prev.map((g, gi) =>
        gi === groupIdx
          ? { ...g, settings: g.settings.map((s) => (s.key === key ? { ...s, value } : s)) }
          : g,
      ),
    );
  };

  const handleSave = async () => {
    setSaving(true);
    await new Promise((r) => setTimeout(r, 600));
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="space-y-6 max-w-3xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">Settings</h1>
          <p className="text-label mt-1">System Configuration</p>
        </div>
        <button
          onClick={handleSave}
          disabled={saving}
          className="btn-primary !py-2 !px-3 !text-xs !font-mono disabled:opacity-50"
        >
          <Save size={12} />
          {saving ? "Saving..." : saved ? "Saved!" : "Save Changes"}
        </button>
      </div>

      <div className="space-y-4">
        {groups.map((group, gi) => (
          <div key={group.title} className="card-glass">
            <p className="text-label mb-4">{group.title}</p>
            <div className="space-y-4">
              {group.settings.map((setting) => (
                <div key={setting.key} className="flex items-center justify-between">
                  <label className="font-mono text-xs text-[#a1a1aa]">
                    {setting.label}
                  </label>
                  {setting.type === "toggle" ? (
                    <button
                      onClick={() => updateSetting(gi, setting.key, !setting.value)}
                      className={`relative h-6 w-10 rounded-full transition-colors ${
                        setting.value ? "bg-[#6366f1]" : "bg-[rgba(255,255,255,0.1)]"
                      }`}
                    >
                      <div
                        className={`absolute top-0.5 h-5 w-5 rounded-full bg-white transition-all ${
                          setting.value ? "left-[18px]" : "left-0.5"
                        }`}
                      />
                    </button>
                  ) : setting.type === "select" ? (
                    <select
                      value={setting.value as string}
                      onChange={(e) => updateSetting(gi, setting.key, e.target.value)}
                      className="rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-1.5 font-mono text-xs text-white outline-none focus:border-[#6366f1]"
                    >
                      {setting.options?.map((opt) => (
                        <option key={opt.value} value={opt.value} className="bg-[#1a1a1a]">
                          {opt.label}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type={setting.type === "number" ? "number" : "text"}
                      value={setting.value as string | number}
                      onChange={(e) =>
                        updateSetting(
                          gi,
                          setting.key,
                          setting.type === "number" ? Number(e.target.value) : e.target.value,
                        )
                      }
                      className="w-32 rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-1.5 font-mono text-xs text-white text-right outline-none focus:border-[#6366f1]"
                    />
                  )}
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* API Configuration */}
      <div className="card-glass">
        <div className="flex items-center justify-between mb-4">
          <p className="text-label">API Configuration</p>
          <button
            onClick={() => setShowSecrets(!showSecrets)}
            className="flex items-center gap-1 text-[#52525b] hover:text-[#a1a1aa] transition-colors"
          >
            {showSecrets ? <EyeOff size={12} /> : <Eye size={12} />}
            <span className="font-mono text-[10px]">{showSecrets ? "Hide" : "Show"}</span>
          </button>
        </div>
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs text-[#a1a1aa]">API URL</span>
            <span className="font-mono text-xs text-[#52525b]">http://localhost:8080</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs text-[#a1a1aa]">WebSocket</span>
            <span className="font-mono text-xs text-[#52525b]">ws://localhost:8080/ws</span>
          </div>
          <div className="flex items-center justify-between">
            <span className="font-mono text-xs text-[#a1a1aa]">API Token</span>
            <span className="font-mono text-xs text-[#52525b]">
              {showSecrets ? "sk-••••••••••••••••" : "••••••••••••••••"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
