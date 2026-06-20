"use client";

import { useCallback, useEffect, useState } from "react";
import {
  activateKillSwitch,
  armKillSwitch,
  getLiveAudit,
  getLiveStatus,
  setLiveMode,
  startLiveEngine,
  stopLiveEngine,
} from "@/lib/api";
import type { AuditEntry, LiveStatusResponse } from "@/types/api";
import { Loader2, Power, PowerOff, Skull, Shield, ShieldOff } from "lucide-react";

type ViewState = "loading" | "disconnected" | "connected" | "error" | "kill-switched";

export default function LivePage() {
  const [status, setStatus] = useState<LiveStatusResponse | null>(null);
  const [viewState, setViewState] = useState<ViewState>("loading");
  const [auditLog, setAuditLog] = useState<AuditEntry[]>([]);
  const [killDialog, setKillDialog] = useState(false);
  const [confirmArm, setConfirmArm] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const s = await getLiveStatus();
      setStatus(s);
      const a = await getLiveAudit(20);
      setAuditLog(a);
      if (s.kill_switch.active) {
        setViewState("kill-switched");
      } else if (s.connected) {
        setViewState("connected");
      } else {
        setViewState("disconnected");
      }
      setError("");
    } catch (e) {
      setViewState("error");
      setError(e instanceof Error ? e.message : "Failed to fetch status");
    }
  }, []);

  useEffect(() => {
    refresh();
    const interval = setInterval(refresh, 5000);
    return () => clearInterval(interval);
  }, [refresh]);

  const handleStart = async () => {
    try {
      const r = await startLiveEngine();
      if (r.connected) setViewState("connected");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start");
    }
  };

  const handleStop = async () => {
    try {
      await stopLiveEngine();
      setViewState("disconnected");
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to stop");
    }
  };

  const handleKill = async () => {
    try {
      await activateKillSwitch("operator");
      setViewState("kill-switched");
      setKillDialog(false);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to activate kill switch");
    }
  };

  const handleArm = async () => {
    try {
      await armKillSwitch();
      setConfirmArm(false);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to arm kill switch");
    }
  };

  const handleModeChange = async (mode: string) => {
    try {
      await setLiveMode(mode);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to change mode");
    }
  };

  // ── Loading state ─────────────────────────────────────────

  if (viewState === "loading") {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-[oklch(0.62_0.19_145)]" />
      </div>
    );
  }

  // ── Error state ───────────────────────────────────────────

  if (viewState === "error" && !status) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center">
          <p className="text-[oklch(0.7_0.15_30)]">Failed to load live trading status</p>
          <p className="mt-2 font-mono text-xs text-[oklch(0.5_0_0)]">{error}</p>
          <button
            onClick={refresh}
            className="mt-4 rounded border border-[oklch(0.3_0_0)] px-4 py-2 text-sm text-[oklch(0.8_0_0)] hover:bg-[oklch(0.2_0_0)]"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const promo = status?.paper_record.promotion;
  const promoOk = promo?.passed ?? false;
  const ks = status?.kill_switch;

  return (
    <div className="space-y-6 p-6">
      {/* ── Header ────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-[oklch(0.92_0_0)]">Live Trading</h1>
        <div className="flex items-center gap-3">
          {/* Connection badge */}
          <span
            className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 font-mono text-xs ${
              viewState === "connected"
                ? "bg-[oklch(0.15_0.05_145)] text-[oklch(0.62_0.19_145)]"
                : viewState === "kill-switched"
                  ? "bg-[oklch(0.2_0.08_30)] text-[oklch(0.7_0.15_30)]"
                  : "bg-[oklch(0.2_0_0)] text-[oklch(0.5_0_0)]"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                viewState === "connected"
                  ? "bg-[oklch(0.62_0.19_145)]"
                  : viewState === "kill-switched"
                    ? "bg-[oklch(0.7_0.15_30)]"
                    : "bg-[oklch(0.5_0_0)]"
              }`}
            />
            {viewState === "connected"
              ? "Connected"
              : viewState === "kill-switched"
                ? "Kill Switch Active"
                : "Disconnected"}
          </span>

          {/* Engine start/stop */}
          {viewState === "disconnected" && (
            <button
              onClick={handleStart}
              className="inline-flex items-center gap-2 rounded bg-[oklch(0.62_0.19_145)] px-4 py-1.5 text-xs font-medium text-black transition-opacity hover:opacity-90"
            >
              <Power size={14} />
              Start Engine
            </button>
          )}
          {(viewState === "connected" || viewState === "kill-switched") && (
            <button
              onClick={handleStop}
              className="inline-flex items-center gap-2 rounded border border-[oklch(0.3_0_0)] px-4 py-1.5 text-xs font-medium text-[oklch(0.7_0_0)] transition-colors hover:bg-[oklch(0.2_0_0)]"
            >
              <PowerOff size={14} />
              Stop Engine
            </button>
          )}
        </div>
      </div>

      {/* ── Error banner ──────────────────────────────────── */}
      {error && (
        <div className="rounded border border-[oklch(0.25_0.06_30)] bg-[oklch(0.12_0.03_30)] px-4 py-2">
          <p className="text-sm text-[oklch(0.7_0.15_30)]">{error}</p>
        </div>
      )}

      {/* ── Two-column layout ─────────────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* ── Main column: Controls + Positions ───────────── */}
        <div className="space-y-6 lg:col-span-2">
          {/* Safety Panel */}
          <div className="rounded-lg border border-[oklch(0.22_0_0)] bg-[oklch(0.12_0_0)] p-4">
            <h2 className="mb-4 font-mono text-xs font-semibold uppercase tracking-wider text-[oklch(0.5_0_0)]">
              Safety Panel
            </h2>

            {/* Kill Switch */}
            <div className="mb-4 flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-[oklch(0.85_0_0)]">Kill Switch</p>
                <p className="font-mono text-xs text-[oklch(0.5_0_0)]">
                  {ks?.active
                    ? `Active — triggered by: ${ks.triggered_by ?? "unknown"}`
                    : "Inactive — trading allowed"}
                </p>
              </div>
              <div className="flex gap-2">
                {!ks?.active ? (
                  <button
                    onClick={() => setKillDialog(true)}
                    className="inline-flex items-center gap-2 rounded bg-[oklch(0.7_0.15_30)] px-4 py-1.5 text-xs font-medium text-black transition-opacity hover:opacity-90"
                  >
                    <Skull size={14} />
                    Activate
                  </button>
                ) : (
                  <button
                    onClick={() => setConfirmArm(true)}
                    className="inline-flex items-center gap-2 rounded border border-[oklch(0.3_0_0)] px-4 py-1.5 text-xs text-[oklch(0.7_0_0)] transition-colors hover:bg-[oklch(0.2_0_0)]"
                  >
                    <Shield size={14} />
                    Re-arm
                  </button>
                )}
              </div>
            </div>

            {/* Mode Selector */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-sm font-medium text-[oklch(0.85_0_0)]">Trading Mode</p>
                <p className="font-mono text-xs text-[oklch(0.5_0_0)]">
                  Current: {status?.mode.replace("_", " ")}
                </p>
              </div>
              <select
                value={status?.mode ?? "human_approval"}
                onChange={(e) => handleModeChange(e.target.value)}
                disabled={ks?.active}
                className="rounded border border-[oklch(0.3_0_0)] bg-[oklch(0.18_0_0)] px-3 py-1.5 font-mono text-xs text-[oklch(0.85_0_0)] disabled:opacity-50"
              >
                <option value="human_approval">Human Approval</option>
                <option value="semi">Semi-Autonomous</option>
                <option value="auto">Full Auto</option>
              </select>
            </div>
          </div>

          {/* Paper Record */}
          <div className="rounded-lg border border-[oklch(0.22_0_0)] bg-[oklch(0.12_0_0)] p-4">
            <h2 className="mb-4 font-mono text-xs font-semibold uppercase tracking-wider text-[oklch(0.5_0_0)]">
              Promotion Gate
            </h2>
            {promo && (
              <div className="space-y-2">
                <div>
                  <div className="mb-1 flex justify-between font-mono text-xs">
                    <span className="text-[oklch(0.6_0_0)]">Paper Trades</span>
                    <span
                      className={
                        promo.trades.current >= promo.trades.required
                          ? "text-[oklch(0.62_0.19_145)]"
                          : "text-[oklch(0.7_0.15_30)]"
                      }
                    >
                      {promo.trades.current}/{promo.trades.required}
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-[oklch(0.22_0_0)]">
                    <div
                      className="h-full rounded-full bg-[oklch(0.62_0.19_145)] transition-all"
                      style={{
                        width: `${Math.min(100, (promo.trades.current / promo.trades.required) * 100)}%`,
                      }}
                    />
                  </div>
                </div>
                <div>
                  <div className="mb-1 flex justify-between font-mono text-xs">
                    <span className="text-[oklch(0.6_0_0)]">Paper Days</span>
                    <span
                      className={
                        promo.days.current >= promo.days.required
                          ? "text-[oklch(0.62_0.19_145)]"
                          : "text-[oklch(0.7_0.15_30)]"
                      }
                    >
                      {promo.days.current}/{promo.days.required}
                    </span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-[oklch(0.22_0_0)]">
                    <div
                      className="h-full rounded-full bg-[oklch(0.62_0.19_145)] transition-all"
                      style={{
                        width: `${Math.min(100, (promo.days.current / promo.days.required) * 100)}%`,
                      }}
                    />
                  </div>
                </div>
                <p className="pt-1 font-mono text-xs text-[oklch(0.5_0_0)]">
                  {promoOk
                    ? "✓ Promotion requirements met"
                    : "Paper record insufficient for auto mode"}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* ── Sidebar: Exchange info + Audit ──────────────── */}
        <div className="space-y-6">
          {/* Exchange Info */}
          <div className="rounded-lg border border-[oklch(0.22_0_0)] bg-[oklch(0.12_0_0)] p-4">
            <h2 className="mb-3 font-mono text-xs font-semibold uppercase tracking-wider text-[oklch(0.5_0_0)]">
              Exchange
            </h2>
            <div className="space-y-2">
              <div className="flex justify-between font-mono text-xs">
                <span className="text-[oklch(0.6_0_0)]">Exchange</span>
                <span className="text-[oklch(0.85_0_0)]">{status?.exchange ?? "—"}</span>
              </div>
              <div className="flex justify-between font-mono text-xs">
                <span className="text-[oklch(0.6_0_0)]">Running</span>
                <span
                  className={
                    status?.running
                      ? "text-[oklch(0.62_0.19_145)]"
                      : "text-[oklch(0.5_0_0)]"
                  }
                >
                  {status?.running ? "Yes" : "No"}
                </span>
              </div>
              <div className="flex justify-between font-mono text-xs">
                <span className="text-[oklch(0.6_0_0)]">Max Drawdown</span>
                <span className="text-[oklch(0.85_0_0)]">
                  {ks?.max_drawdown_pct ?? 15}%
                </span>
              </div>
            </div>
          </div>

          {/* Mode Status */}
          <div className="rounded-lg border border-[oklch(0.22_0_0)] bg-[oklch(0.12_0_0)] p-4">
            <h2 className="mb-3 font-mono text-xs font-semibold uppercase tracking-wider text-[oklch(0.5_0_0)]">
              Mode Status
            </h2>
            <div className="flex items-center gap-2">
              {status?.mode === "human_approval" ? (
                <ShieldOff size={16} className="text-[oklch(0.7_0.15_30)]" />
              ) : (
                <Shield size={16} className="text-[oklch(0.62_0.19_145)]" />
              )}
              <span className="font-mono text-sm text-[oklch(0.85_0_0)]">
                {status?.mode === "human_approval"
                  ? "Human Approval Mode"
                  : status?.mode === "semi"
                    ? "Semi-Autonomous"
                    : "Full Auto"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* ── Audit Log ──────────────────────────────────────── */}
      <div className="rounded-lg border border-[oklch(0.22_0_0)] bg-[oklch(0.12_0_0)] p-4">
        <h2 className="mb-4 font-mono text-xs font-semibold uppercase tracking-wider text-[oklch(0.5_0_0)]">
          Recent Audit Log
        </h2>
        {auditLog.length === 0 ? (
          <p className="font-mono text-xs text-[oklch(0.4_0_0)]">No audit entries yet</p>
        ) : (
          <div className="space-y-2">
            {auditLog.map((entry, i) => (
              <div
                key={i}
                className="rounded border border-[oklch(0.2_0_0)] bg-[oklch(0.09_0_0)] px-3 py-2"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-[oklch(0.62_0.19_145)]">
                    {entry.order_intent?.symbol as string ?? "—"}
                  </span>
                  <span className="font-mono text-[10px] text-[oklch(0.4_0_0)]">
                    {entry.timestamp
                      ? new Date(entry.timestamp).toLocaleTimeString()
                      : ""}
                  </span>
                </div>
                <div className="mt-1 flex items-center gap-2">
                  <span className="font-mono text-[10px] text-[oklch(0.5_0_0)]">
                    {entry.order_intent?.side as string ?? ""}{" "}
                    {entry.order_intent?.quantity as number ?? 0}
                  </span>
                  <span
                    className={`font-mono text-[10px] ${
                      entry.order_result
                        ? "text-[oklch(0.62_0.19_145)]"
                        : "text-[oklch(0.7_0.15_30)]"
                    }`}
                  >
                    {entry.order_result
                      ? (entry.order_result.status as string) ?? "executed"
                      : "pending"}
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Kill confirmation dialog ───────────────────────── */}
      {killDialog && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-96 rounded-lg border border-[oklch(0.25_0.06_30)] bg-[oklch(0.12_0_0)] p-6 shadow-2xl">
            <h3 className="text-lg font-semibold text-[oklch(0.7_0.15_30)]">
              Activate Kill Switch?
            </h3>
            <p className="mt-2 text-sm text-[oklch(0.6_0_0)]">
              This will immediately halt all live order placement. You must manually re-arm
              to resume.
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={() => setKillDialog(false)}
                className="rounded border border-[oklch(0.3_0_0)] px-4 py-2 text-sm text-[oklch(0.7_0_0)] hover:bg-[oklch(0.2_0_0)]"
              >
                Cancel
              </button>
              <button
                onClick={handleKill}
                className="rounded bg-[oklch(0.7_0.15_30)] px-4 py-2 text-sm font-medium text-black hover:opacity-90"
              >
                Activate Kill Switch
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Arm confirmation dialog ─────────────────────────── */}
      {confirmArm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-96 rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.12_0_0)] p-6 shadow-2xl">
            <h3 className="text-lg font-semibold text-[oklch(0.62_0.19_145)]">
              Re-arm Kill Switch?
            </h3>
            <p className="mt-2 text-sm text-[oklch(0.6_0_0)]">
              Confirm that you want to re-arm the kill switch and allow live trading to
              resume.
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={() => setConfirmArm(false)}
                className="rounded border border-[oklch(0.3_0_0)] px-4 py-2 text-sm text-[oklch(0.7_0_0)] hover:bg-[oklch(0.2_0_0)]"
              >
                Cancel
              </button>
              <button
                onClick={handleArm}
                className="rounded bg-[oklch(0.62_0.19_145)] px-4 py-2 text-sm font-medium text-black hover:opacity-90"
              >
                Re-arm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
