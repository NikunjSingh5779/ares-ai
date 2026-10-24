"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import {
  activateKillSwitch,
  armKillSwitch,
  getLiveAudit,
  getLiveStatus,
  getSettings,
  setLiveMode,
  startLiveEngine,
  stopLiveEngine,
} from "@/lib/api";
import type { AuditEntry, LiveStatusResponse } from "@/types/api";
import { Loader2, Power, PowerOff, Skull, Shield, ShieldOff } from "lucide-react";

type ViewState = "loading" | "disconnected" | "connected" | "error" | "kill-switched";

function progressPercent(current: number, required: number): number {
  if (!Number.isFinite(current) || !Number.isFinite(required) || required <= 0) {
    return 0;
  }
  return Math.min(100, Math.max(0, (current / required) * 100));
}

export default function LivePage() {
  const [status, setStatus] = useState<LiveStatusResponse | null>(null);
  const [viewState, setViewState] = useState<ViewState>("loading");
  const [auditLog, setAuditLog] = useState<AuditEntry[]>([]);
  const [killDialog, setKillDialog] = useState(false);
  const [confirmArm, setConfirmArm] = useState(false);
  const [error, setError] = useState("");
  const [refreshSeconds, setRefreshSeconds] = useState(5);
  const refreshInFlightRef = useRef<Promise<void> | null>(null);
  const refreshAbortRef = useRef<AbortController | null>(null);

  const refresh = useCallback((): Promise<void> => {
    const inFlight = refreshInFlightRef.current;
    if (inFlight) return inFlight;

    const controller = new AbortController();
    refreshAbortRef.current = controller;

    const run = async () => {
      try {
        const [nextStatus, nextAudit] = await Promise.all([
          getLiveStatus(controller.signal),
          getLiveAudit(20, controller.signal),
        ]);
        if (controller.signal.aborted) return;

        setStatus(nextStatus);
        setAuditLog(nextAudit);
        if (nextStatus.kill_switch.active) {
          setViewState("kill-switched");
        } else if (nextStatus.connected) {
          setViewState("connected");
        } else {
          setViewState("disconnected");
        }
        setError("");
      } catch (e) {
        if (controller.signal.aborted) return;
        // Keep the last known status visible during a transient poll failure;
        // only the initial load has no status to fall back to.
        setViewState((previous) => (previous === "loading" ? "error" : previous));
        setError(e instanceof Error ? e.message : "Failed to fetch status");
      } finally {
        if (refreshAbortRef.current === controller) {
          refreshAbortRef.current = null;
        }
      }
    };

    const promise = run();
    refreshInFlightRef.current = promise;
    void promise.finally(() => {
      if (refreshInFlightRef.current === promise) {
        refreshInFlightRef.current = null;
      }
    });
    return promise;
  }, []);

  // Discard a poll that started before a control action, then fetch the new
  // state immediately instead of waiting for the next interval.
  const forceRefresh = useCallback((): Promise<void> => {
    refreshAbortRef.current?.abort();
    refreshInFlightRef.current = null;
    return refresh();
  }, [refresh]);

  useEffect(() => {
    const controller = new AbortController();
    getSettings(controller.signal)
      .then((settings) => setRefreshSeconds(settings.preferences.live_refresh_seconds))
      .catch(() => {});
    return () => controller.abort();
  }, []);

  useEffect(() => {
    return () => {
      refreshAbortRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    let interval: ReturnType<typeof setInterval> | null = null;

    const tick = () => {
      if (document.visibilityState === "visible") {
        void refresh();
      }
    };

    const start = () => {
      if (interval !== null) return;
      tick();
      interval = setInterval(tick, Math.max(1, refreshSeconds) * 1000);
    };

    const stop = () => {
      if (interval !== null) {
        clearInterval(interval);
        interval = null;
      }
    };

    const handleVisibilityChange = () => {
      if (document.hidden) stop();
      else start();
    };

    if (!document.hidden) start();
    document.addEventListener("visibilitychange", handleVisibilityChange);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", handleVisibilityChange);
    };
  }, [refresh, refreshSeconds]);

  const handleStart = async () => {
    try {
      const r = await startLiveEngine();
      if (r.connected) setViewState("connected");
      await forceRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start");
    }
  };

  const handleStop = async () => {
    try {
      await stopLiveEngine();
      setViewState("disconnected");
      await forceRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to stop");
    }
  };

  const handleKill = async () => {
    try {
      await activateKillSwitch("operator");
      setViewState("kill-switched");
      setKillDialog(false);
      await forceRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to activate kill switch");
    }
  };

  const handleArm = async () => {
    try {
      await armKillSwitch();
      setConfirmArm(false);
      await forceRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to arm kill switch");
    }
  };

  const handleModeChange = async (mode: string) => {
    try {
      await setLiveMode(mode);
      await forceRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to change mode");
    }
  };

  // ── Loading state ─────────────────────────────────────────
  if (viewState === "loading") {
    return (
      <div
        className="flex h-full items-center justify-center"
        role="status"
        aria-live="polite"
      >
        <h1 className="sr-only">Live Trading</h1>
        <Loader2 className="h-8 w-8 animate-spin text-[#6366f1]" aria-hidden="true" />
        <span className="sr-only">Loading live trading status</span>
      </div>
    );
  }

  // ── Error state ───────────────────────────────────────────
  if (viewState === "error" && !status) {
    return (
      <div className="flex h-full items-center justify-center">
        <div className="text-center" role="alert">
          <h1 className="sr-only">Live Trading</h1>
          <p className="text-[#ef4444] font-medium">Failed to load live trading status</p>
          <p className="mt-2 font-mono text-xs text-[#a1a1aa]">{error}</p>
          <button
            onClick={refresh}
            className="btn-ghost !text-sm mt-4"
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
    <div className="space-y-6">
      {/* ── Header ────────────────────────────────────────── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">Live Trading</h1>
          <p className="text-label mt-1">Engine Control & Safety Management</p>
          <p className="mt-1 font-mono text-[10px] text-[#a1a1aa]">
            Auto-refresh every {refreshSeconds}s
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Connection badge */}
          <span
            role="status"
            aria-live="polite"
            className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-xs ${
              viewState === "connected"
                ? "bg-[rgba(34,197,94,0.1)] text-[#22c55e] border-[rgba(34,197,94,0.2)]"
                : viewState === "kill-switched"
                  ? "bg-[rgba(239,68,68,0.1)] text-[#ef4444] border-[rgba(239,68,68,0.2)]"
                  : "bg-[rgba(255,255,255,0.04)] text-[#8b8b93] border-[rgba(255,255,255,0.08)]"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                viewState === "connected"
                  ? "bg-[#22c55e] animate-pulse"
                  : viewState === "kill-switched"
                    ? "bg-[#ef4444]"
                    : "bg-[#8b8b93]"
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
              className="btn-primary !py-2 !px-3 !text-xs"
            >
              <Power size={14} />
              Start Engine
            </button>
          )}
          {(viewState === "connected" || viewState === "kill-switched") && (
            <button
              onClick={handleStop}
              className="btn-ghost !py-2 !px-3 !text-xs"
            >
              <PowerOff size={14} />
              Stop Engine
            </button>
          )}
        </div>
      </div>

      {/* ── Error banner ──────────────────────────────────── */}
      {error && (
        <div
          role="alert"
          className="rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3"
        >
          <p className="font-mono text-xs text-[#ef4444]">{error}</p>
        </div>
      )}

      {/* ── Two-column layout ─────────────────────────────── */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* ── Main column: Controls + Positions ───────────── */}
        <div className="space-y-6 lg:col-span-2">
          {/* Safety Panel */}
          <div className="card-glass">
            <h2 className="text-label mb-5">
              Safety Panel
            </h2>

            {/* Kill Switch */}
            <div className="mb-5 flex items-center justify-between">
              <div>
                <p className="text-sm font-semibold text-white">Kill Switch</p>
                <p className="font-mono text-xs text-[#a1a1aa] mt-0.5">
                  {ks?.active
                    ? `Active — triggered by: ${ks.triggered_by ?? "unknown"}`
                    : "Inactive — trading allowed"}
                </p>
              </div>
              <div className="flex gap-2">
                {!ks?.active ? (
                  <button
                    onClick={() => setKillDialog(true)}
                    className="inline-flex items-center gap-2 rounded-lg bg-[#ef4444] px-4 py-2 text-xs font-semibold text-white transition-all hover:bg-[#dc2626] hover:shadow-lg hover:shadow-[rgba(239,68,68,0.25)]"
                  >
                    <Skull size={14} />
                    Activate
                  </button>
                ) : (
                  <button
                    onClick={() => setConfirmArm(true)}
                    className="btn-ghost !py-2 !text-xs"
                  >
                    <Shield size={14} />
                    Re-arm
                  </button>
                )}
              </div>
            </div>

            {/* Mode Selector */}
            <div className="flex items-center justify-between border-t border-[rgba(255,255,255,0.06)] pt-5">
              <div>
                <label
                  htmlFor="trading-mode"
                  className="text-sm font-semibold text-white"
                >
                  Trading Mode
                </label>
                <p
                  id="trading-mode-current"
                  className="font-mono text-xs text-[#a1a1aa] mt-0.5"
                >
                  Current: {status?.mode.replace("_", " ")}
                </p>
              </div>
              <select
                id="trading-mode"
                aria-describedby="trading-mode-current"
                value={status?.mode ?? "human_approval"}
                onChange={(e) => handleModeChange(e.target.value)}
                disabled={ks?.active}
                className="rounded-lg border border-[rgba(255,255,255,0.1)] bg-[rgba(255,255,255,0.04)] px-3 py-2 font-mono text-xs text-white disabled:opacity-50 focus:border-[#6366f1] focus:outline-none focus:ring-1 focus:ring-[rgba(99,102,241,0.3)]"
              >
                <option value="human_approval">Human Approval</option>
                <option value="semi">Semi-Autonomous</option>
                <option value="auto">Full Auto</option>
              </select>
            </div>
          </div>

          {/* Paper Record */}
          <div className="card-glass">
            <h2 className="text-label mb-5">
              Promotion Gate
            </h2>
            {promo && (
              <div className="space-y-4">
                <div>
                  <div className="mb-2 flex justify-between font-mono text-xs">
                    <span className="text-[#a1a1aa]">Paper Trades</span>
                    <span
                      className={
                        promo.trades.current >= promo.trades.required
                          ? "text-[#22c55e] font-semibold"
                          : "text-[#f59e0b] font-semibold"
                      }
                    >
                      {promo.trades.current}/{promo.trades.required}
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-[rgba(255,255,255,0.06)]">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-[#6366f1] to-[#22c55e] transition-all duration-500"
                      style={{
                        width: `${progressPercent(promo.trades.current, promo.trades.required)}%`,
                      }}
                    />
                  </div>
                </div>
                <div>
                  <div className="mb-2 flex justify-between font-mono text-xs">
                    <span className="text-[#a1a1aa]">Paper Days</span>
                    <span
                      className={
                        promo.days.current >= promo.days.required
                          ? "text-[#22c55e] font-semibold"
                          : "text-[#f59e0b] font-semibold"
                      }
                    >
                      {promo.days.current}/{promo.days.required}
                    </span>
                  </div>
                  <div className="h-2 overflow-hidden rounded-full bg-[rgba(255,255,255,0.06)]">
                    <div
                      className="h-full rounded-full bg-gradient-to-r from-[#6366f1] to-[#22c55e] transition-all duration-500"
                      style={{
                        width: `${progressPercent(promo.days.current, promo.days.required)}%`,
                      }}
                    />
                  </div>
                </div>
                <p className={`pt-2 font-mono text-xs ${promoOk ? "text-[#22c55e]" : "text-[#a1a1aa]"}`}>
                  {promoOk
                    ? "✓ Promotion requirements met"
                    : "Paper record insufficient for auto mode"}
                </p>
              </div>
            )}
          </div>
        </div>

        {/* ── Sidebar: Exchange info + Mode ──────────────── */}
        <div className="space-y-6">
          {/* Exchange Info */}
          <div className="card-glass">
            <h2 className="text-label mb-4">
              Exchange
            </h2>
            <div className="space-y-3">
              <div className="flex justify-between font-mono text-xs">
                <span className="text-[#a1a1aa]">Exchange</span>
                <span className="text-white font-medium">{status?.exchange ?? "—"}</span>
              </div>
              <div className="flex justify-between font-mono text-xs">
                <span className="text-[#a1a1aa]">Running</span>
                <span
                  className={
                    status?.running
                      ? "text-[#22c55e] font-medium"
                      : "text-[#8b8b93]"
                  }
                >
                  {status?.running ? "Yes" : "No"}
                </span>
              </div>
              <div className="flex justify-between font-mono text-xs">
                <span className="text-[#a1a1aa]">Max Drawdown</span>
                <span className="text-white font-medium">
                  {ks?.max_drawdown_pct ?? 15}%
                </span>
              </div>
            </div>
          </div>

          {/* Mode Status */}
          <div className="card-glass">
            <h2 className="text-label mb-4">
              Mode Status
            </h2>
            <div className="flex items-center gap-3">
              {status?.mode === "human_approval" ? (
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[rgba(245,158,11,0.12)]">
                  <ShieldOff size={18} className="text-[#f59e0b]" />
                </div>
              ) : (
                <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-[rgba(34,197,94,0.12)]">
                  <Shield size={18} className="text-[#22c55e]" />
                </div>
              )}
              <div>
                <span className="font-sans text-sm font-semibold text-white">
                  {status?.mode === "human_approval"
                    ? "Human Approval"
                    : status?.mode === "semi"
                      ? "Semi-Autonomous"
                      : "Full Auto"}
                </span>
                <p className="font-mono text-[10px] text-[#8b8b93] mt-0.5">
                  {status?.mode === "human_approval"
                    ? "Orders require manual confirmation"
                    : status?.mode === "semi"
                      ? "Auto within risk limits"
                      : "Fully automated execution"}
                </p>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Audit Log ──────────────────────────────────────── */}
      <div className="card-glass !p-0 overflow-hidden">
        <div className="px-5 py-4 border-b border-[rgba(255,255,255,0.06)]">
          <h2 className="text-label">
            Recent Audit Log
          </h2>
        </div>
        {auditLog.length === 0 ? (
          <p className="font-mono text-xs text-[#8b8b93] px-5 py-6">No audit entries yet</p>
        ) : (
          <div role="list" className="divide-y divide-[rgba(255,255,255,0.04)]">
            {auditLog.map((entry, i) => (
              <div
                role="listitem"
                key={i}
                className="px-5 py-3 transition-colors hover:bg-[rgba(255,255,255,0.02)]"
              >
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs font-medium text-[#6366f1]">
                    {entry.order_intent?.symbol as string ?? "—"}
                  </span>
                  <span className="font-mono text-[10px] text-[#8b8b93]">
                    {entry.timestamp
                      ? new Date(entry.timestamp).toLocaleTimeString()
                      : ""}
                  </span>
                </div>
                <div className="mt-1 flex items-center gap-3">
                  <span className="font-mono text-[10px] text-[#a1a1aa]">
                    {entry.order_intent?.side as string ?? ""}{" "}
                    {entry.order_intent?.quantity as number ?? 0}
                  </span>
                  <span
                    className={`font-mono text-[10px] font-medium ${
                      entry.order_result
                        ? "text-[#22c55e]"
                        : "text-[#f59e0b]"
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="kill-dialog-title"
            aria-describedby="kill-dialog-description"
            onKeyDown={(event) => {
              if (event.key === "Escape") setKillDialog(false);
            }}
            className="w-96 rounded-2xl border border-[rgba(239,68,68,0.2)] bg-[#111111] p-6 shadow-2xl shadow-black/50"
          >
            <h3 id="kill-dialog-title" className="text-lg font-bold text-[#ef4444]">
              Activate Kill Switch?
            </h3>
            <p
              id="kill-dialog-description"
              className="mt-3 text-sm text-[#a1a1aa] leading-relaxed"
            >
              This will immediately halt all live order placement. You must manually re-arm
              to resume.
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={() => setKillDialog(false)}
                autoFocus
                className="btn-ghost !py-2 !text-sm"
              >
                Cancel
              </button>
              <button
                onClick={handleKill}
                className="inline-flex items-center gap-2 rounded-lg bg-[#ef4444] px-4 py-2 text-sm font-semibold text-white hover:bg-[#dc2626] transition-colors"
              >
                Activate Kill Switch
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Arm confirmation dialog ─────────────────────────── */}
      {confirmArm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div
            role="dialog"
            aria-modal="true"
            aria-labelledby="arm-dialog-title"
            aria-describedby="arm-dialog-description"
            onKeyDown={(event) => {
              if (event.key === "Escape") setConfirmArm(false);
            }}
            className="w-96 rounded-2xl border border-[rgba(34,197,94,0.2)] bg-[#111111] p-6 shadow-2xl shadow-black/50"
          >
            <h3 id="arm-dialog-title" className="text-lg font-bold text-[#22c55e]">
              Re-arm Kill Switch?
            </h3>
            <p
              id="arm-dialog-description"
              className="mt-3 text-sm text-[#a1a1aa] leading-relaxed"
            >
              Confirm that you want to re-arm the kill switch and allow live trading to
              resume.
            </p>
            <div className="mt-6 flex justify-end gap-3">
              <button
                onClick={() => setConfirmArm(false)}
                autoFocus
                className="btn-ghost !py-2 !text-sm"
              >
                Cancel
              </button>
              <button
                onClick={handleArm}
                className="btn-primary !py-2 !text-sm"
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
