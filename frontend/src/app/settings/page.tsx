"use client";

import { useEffect, useState, type FormEvent } from "react";
import { AlertTriangle, Check, Loader2, RefreshCw, Save, Shield } from "lucide-react";
import { API_BASE_URL, getSettings, updateSettingsPreferences } from "@/lib/api";
import type { DashboardPreferences, SafetyLimits, SettingsResponse } from "@/types/api";

const REFRESH_OPTIONS = [5, 10, 15, 30] as const;
const SYMBOL_PATTERN = /^[A-Z0-9^.=:/-]{1,20}$/;
const SYMBOL_HELP = "1-20 characters: letters, numbers, or . ^ = : / -";

function errorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback;
}

export default function SettingsPage() {
  const [settings, setSettings] = useState<SettingsResponse | null>(null);
  const [preferences, setPreferences] = useState<DashboardPreferences | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");
  const [saved, setSaved] = useState(false);
  const [reloadToken, setReloadToken] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    let cancelled = false;
    setLoading(true);
    setLoadError("");

    getSettings(controller.signal)
      .then((data) => {
        if (cancelled) return;
        setSettings(data);
        setPreferences(data.preferences);
      })
      .catch((error: unknown) => {
        if (cancelled || controller.signal.aborted) return;
        setLoadError(errorMessage(error, "Failed to load settings"));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [reloadToken]);

  useEffect(() => {
    if (!saved) return;
    const timeout = window.setTimeout(() => setSaved(false), 2500);
    return () => window.clearTimeout(timeout);
  }, [saved]);

  function markDirty() {
    setSaved(false);
    setSaveError("");
  }

  async function handleSave(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!preferences || saving) return;

    const normalized = preferences.default_symbol.trim().toUpperCase();
    if (!SYMBOL_PATTERN.test(normalized)) return;

    setSaving(true);
    setSaveError("");
    setSaved(false);
    try {
      const updated = await updateSettingsPreferences({
        default_symbol: normalized,
        live_refresh_seconds: preferences.live_refresh_seconds,
      });
      setSettings(updated);
      setPreferences(updated.preferences);
      setSaved(true);
    } catch (error) {
      setSaveError(errorMessage(error, "Failed to save settings"));
    } finally {
      setSaving(false);
    }
  }

  if (!settings || !preferences) {
    if (loading) {
      return (
        <div
          className="flex items-center justify-center gap-2 py-20 font-mono text-xs text-[#a1a1aa]"
          role="status"
          aria-live="polite"
        >
          <Loader2 size={16} className="animate-spin text-[#6366f1]" />
          Loading settings…
        </div>
      );
    }

    return (
      <div className="mx-auto max-w-xl space-y-4 py-20" role="alert">
        <div className="flex items-center gap-2 text-[#ef4444]">
          <AlertTriangle size={18} />
          <h1 className="text-lg font-semibold">Settings unavailable</h1>
        </div>
        <p className="font-mono text-xs text-[#a1a1aa]">
          {loadError || "The settings store did not respond."}
        </p>
        <button
          type="button"
          onClick={() => setReloadToken((token) => token + 1)}
          className="btn-ghost !py-2 !px-3 !text-xs !font-mono"
        >
          <RefreshCw size={12} />
          Retry
        </button>
      </div>
    );
  }

  const normalizedSymbol = preferences.default_symbol.trim().toUpperCase();
  const symbolValid = SYMBOL_PATTERN.test(normalizedSymbol);
  const isDirty =
    normalizedSymbol !== settings.preferences.default_symbol ||
    preferences.live_refresh_seconds !== settings.preferences.live_refresh_seconds;

  const safetyRows = safetyRowsFor(settings.safety);

  return (
    <div className="max-w-3xl space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-heading text-xl text-white">Settings</h1>
          <p className="text-label mt-1">Runtime configuration</p>
        </div>
        <button
          type="submit"
          form="settings-form"
          disabled={!isDirty || !symbolValid || saving}
          className="btn-primary !py-2 !px-3 !text-xs !font-mono disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? (
            <Loader2 size={12} className="animate-spin" />
          ) : saved ? (
            <Check size={12} />
          ) : (
            <Save size={12} />
          )}
          {saving ? "Saving..." : saved ? "Saved" : "Save changes"}
        </button>
      </div>

      <div aria-live="polite" role="status">
        {saved && (
          <div className="flex items-center gap-2 rounded-xl border border-[rgba(34,197,94,0.2)] bg-[rgba(34,197,94,0.08)] px-4 py-3">
            <Check size={14} className="text-[#22c55e]" />
            <span className="font-mono text-xs text-[#22c55e]">
              Preferences saved and will survive a backend restart.
            </span>
          </div>
        )}
      </div>

      {(loadError || saveError) && (
        <div
          className="flex items-start gap-2 rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3"
          role="alert"
        >
          <AlertTriangle size={14} className="mt-0.5 shrink-0 text-[#ef4444]" />
          <div className="min-w-0 flex-1">
            <span className="font-mono text-xs text-[#ef4444]">{saveError || loadError}</span>
            {loadError && (
              <button
                type="button"
                onClick={() => setReloadToken((token) => token + 1)}
                className="ml-3 font-mono text-xs text-[#a1a1aa] underline decoration-dotted hover:text-white"
              >
                Retry load
              </button>
            )}
          </div>
        </div>
      )}

      <form id="settings-form" onSubmit={handleSave} className="space-y-4">
        <section className="card-glass" aria-labelledby="safety-heading">
          <div className="mb-1 flex items-center gap-2">
            <Shield size={14} className="text-[#6366f1]" />
            <h2 id="safety-heading" className="text-label">
              Enforced safety limits
            </h2>
          </div>
          <p className="mb-4 font-mono text-[11px] leading-relaxed text-[#a1a1aa]">
            Read-only. These come from the trading logic and cannot be changed from the
            dashboard.
          </p>
          <dl className="divide-y divide-[rgba(255,255,255,0.06)]">
            {safetyRows.map((row) => (
              <div
                key={row.label}
                className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-1 py-3"
              >
                <dt className="font-mono text-xs text-[#d4d4d8]">{row.label}</dt>
                <dd className="row-span-2 shrink-0 text-right font-mono text-xs text-white">
                  {row.value}
                </dd>
                <dd className="font-mono text-[11px] text-[#a1a1aa]">{row.detail}</dd>
              </div>
            ))}
          </dl>
        </section>

        <section className="card-glass" aria-labelledby="preferences-heading">
          <h2 id="preferences-heading" className="text-label mb-1">
            Dashboard preferences
          </h2>
          <p className="mb-4 font-mono text-[11px] leading-relaxed text-[#a1a1aa]">
            Saved in PostgreSQL. These affect presentation only; they never size or approve
            a trade.
          </p>

          <div className="space-y-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="max-w-sm">
                <label
                  htmlFor="default-symbol"
                  className="font-mono text-xs text-[#d4d4d8]"
                >
                  Default symbol
                </label>
                <p id="default-symbol-help" className="mt-1 font-mono text-[11px] text-[#a1a1aa]">
                  Used by dashboard analysis and the initial markets chart. {SYMBOL_HELP}
                </p>
                {!symbolValid && (
                  <p id="default-symbol-error" className="mt-1 font-mono text-[11px] text-[#ef4444]">
                    Enter a valid ticker before saving.
                  </p>
                )}
              </div>
              <input
                id="default-symbol"
                type="text"
                value={preferences.default_symbol}
                onChange={(event) => {
                  markDirty();
                  setPreferences({ ...preferences, default_symbol: event.target.value });
                }}
                spellCheck={false}
                autoComplete="off"
                aria-invalid={!symbolValid}
                aria-describedby={
                  symbolValid ? "default-symbol-help" : "default-symbol-help default-symbol-error"
                }
                className="w-40 rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-1.5 font-mono text-xs uppercase text-white outline-none focus:border-[#6366f1]"
              />
            </div>

            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="max-w-sm">
                <label
                  htmlFor="live-refresh"
                  className="font-mono text-xs text-[#d4d4d8]"
                >
                  Live status refresh
                </label>
                <p id="live-refresh-help" className="mt-1 font-mono text-[11px] text-[#a1a1aa]">
                  How often /live checks engine and kill-switch state.
                </p>
              </div>
              <select
                id="live-refresh"
                value={preferences.live_refresh_seconds}
                onChange={(event) => {
                  markDirty();
                  setPreferences({
                    ...preferences,
                    live_refresh_seconds: Number(event.target.value),
                  });
                }}
                aria-describedby="live-refresh-help"
                className="w-40 rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] px-3 py-1.5 font-mono text-xs text-white outline-none focus:border-[#6366f1]"
              >
                {REFRESH_OPTIONS.map((seconds) => (
                  <option key={seconds} value={seconds} className="bg-[#1a1a1a]">
                    {seconds} seconds
                  </option>
                ))}
              </select>
            </div>
          </div>
        </section>
      </form>

      <section className="card-glass" aria-labelledby="api-heading">
        <h2 id="api-heading" className="text-label mb-1">
          API connection
        </h2>
        <p className="mb-4 font-mono text-[11px] leading-relaxed text-[#a1a1aa]">
          Read from <span className="text-[#d4d4d8]">NEXT_PUBLIC_API_URL</span> at build
          time. The session key is never rendered.
        </p>
        <dl className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <dt className="font-mono text-xs text-[#a1a1aa]">API URL</dt>
            <dd className="break-all font-mono text-xs text-[#d4d4d8]">{API_BASE_URL}</dd>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <dt className="font-mono text-xs text-[#a1a1aa]">Authentication</dt>
            <dd className="font-mono text-xs text-[#d4d4d8]">
              Session API key · stored in this tab only
            </dd>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <dt className="font-mono text-xs text-[#a1a1aa]">Trading mode</dt>
            <dd className="font-mono text-xs text-[#d4d4d8]">
              {settings.safety.live_trading_enabled ? "Live trading enabled" : "Paper trading only"}
            </dd>
          </div>
        </dl>
      </section>
    </div>
  );
}

function safetyRowsFor(safety: SafetyLimits): Array<{ label: string; detail: string; value: string }> {
  return [
    {
      label: "Max position size",
      detail: "Notional cap per paper order, derived from current equity.",
      value: `${safety.max_position_size_pct}%`,
    },
    {
      label: "Max risk score",
      detail: "Risk Agent approval ceiling; higher scores are rejected.",
      value: `${safety.max_risk_score} / 100`,
    },
    {
      label: "Minimum consensus confidence",
      detail: "Both Market Analyst and Quant must be above this value.",
      value: `> ${safety.min_consensus_confidence_pct}%`,
    },
    {
      label: "Live drawdown kill switch",
      detail: "Live trading halts when paper drawdown exceeds this limit.",
      value: `${safety.live_max_drawdown_pct}%`,
    },
    {
      label: "Paper-to-live promotion gate",
      detail: "Minimum paper record before autonomous live modes unlock.",
      value: `${safety.minimum_paper_trades} trades / ${safety.minimum_paper_days} days`,
    },
  ];
}
