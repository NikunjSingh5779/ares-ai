"use client";

import { useEffect, useState } from "react";
import { TrendingUp, RefreshCw } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import { getSignal } from "@/lib/api";
import type { SignalResponse, AgentState } from "@/types/api";

export default function SignalsPage() {
  const [signal, setSignal] = useState<SignalResponse | null>(null);
  const [fullState, setFullState] = useState<AgentState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadSignal() {
    setLoading(true);
    setError(null);
    try {
      const result = await getSignal("BTC-USD", "Signal analysis");
      setSignal(result);
    } catch {
      setError("Could not fetch signal");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadSignal();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-mono text-xl font-semibold text-[oklch(0.92_0_0)]">
            Signals
          </h1>
          <p className="font-mono text-xs text-[oklch(0.6_0_0)]">
            Agent Pipeline Signal History
          </p>
        </div>
        <button
          onClick={loadSignal}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-md bg-[oklch(0.62_0.19_145)] px-3 py-1.5 font-mono text-xs font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          <TrendingUp size={12} />
          {loading ? "Loading..." : "Run Signal"}
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-[oklch(0.25_0.08_30)] bg-[oklch(0.25_0.08_30)] px-4 py-2">
          <p className="font-mono text-xs text-[oklch(0.55_0.22_30)]">{error}</p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Signal Status Card */}
        <div className="rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.18_0.01_145)] p-4">
          <p className="mb-3 font-mono text-xs font-medium text-[oklch(0.6_0_0)] uppercase tracking-wider">
            Signal Status
          </p>
          {signal ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[oklch(0.6_0_0)]">Status</span>
                <StatusBadge status={signal.approved ? "approved" : "rejected"} />
              </div>
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[oklch(0.6_0_0)]">Direction</span>
                <span
                  className={`font-mono text-sm font-semibold ${
                    signal.direction === "long"
                      ? "text-[oklch(0.62_0.19_145)]"
                      : signal.direction === "short"
                        ? "text-[oklch(0.55_0.22_30)]"
                        : "text-[oklch(0.6_0_0)]"
                  }`}
                >
                  {signal.direction.toUpperCase()}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[oklch(0.6_0_0)]">Confidence</span>
                <span className="font-mono text-sm font-semibold text-[oklch(0.92_0_0)]">
                  {signal.confidence.toFixed(0)}%
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[oklch(0.6_0_0)]">Executed</span>
                <StatusBadge status={signal.executed ? "ok" : "skipped"} label={signal.executed ? "Yes" : "No"} />
              </div>
              {signal.rationale && (
                <>
                  <hr className="border-[oklch(0.25_0_0)]" />
                  <p className="font-mono text-xs text-[oklch(0.5_0_0)] leading-relaxed">
                    {signal.rationale}
                  </p>
                </>
              )}
            </div>
          ) : loading ? (
            <div className="flex justify-center py-8">
              <RefreshCw size={16} className="animate-spin text-[oklch(0.6_0_0)]" />
            </div>
          ) : (
            <p className="font-mono text-sm text-[oklch(0.38_0_0)] py-4">
              No signal data yet. Run a signal to see results.
            </p>
          )}
        </div>

        {/* Pipeline Status */}
        <div className="rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.18_0.01_145)] p-4">
          <p className="mb-3 font-mono text-xs font-medium text-[oklch(0.6_0_0)] uppercase tracking-wider">
            Pipeline Status
          </p>
          {signal?.pipeline_status ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[oklch(0.6_0_0)]">Completed</span>
                <span className="font-mono text-xs text-[oklch(0.62_0.19_145)]">
                  {signal.pipeline_status.completed_nodes.length}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[oklch(0.6_0_0)]">Failed</span>
                <span className="font-mono text-xs text-[oklch(0.55_0.22_30)]">
                  {signal.pipeline_status.failed_nodes.length}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[oklch(0.6_0_0)]">Skipped</span>
                <span className="font-mono text-xs text-[oklch(0.38_0_0)]">
                  {signal.pipeline_status.skipped_nodes.length}
                </span>
              </div>
              {signal.errors.length > 0 && (
                <div className="mt-2 space-y-1">
                  {signal.errors.map((err, i) => (
                    <div
                      key={i}
                      className="rounded bg-[oklch(0.25_0.08_30)] px-2 py-1 font-mono text-xs text-[oklch(0.55_0.22_30)]"
                    >
                      {err.agent}: {err.error}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="font-mono text-sm text-[oklch(0.38_0_0)] py-4">
              No pipeline has run yet.
            </p>
          )}
        </div>

        {/* Agent Outputs */}
        <div className="rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.18_0.01_145)] p-4">
          <p className="mb-3 font-mono text-xs font-medium text-[oklch(0.6_0_0)] uppercase tracking-wider">
            Latest Run
          </p>
          {signal ? (
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[oklch(0.6_0_0)]">Symbol</span>
                <span className="font-mono text-xs text-[oklch(0.92_0_0)]">{signal.symbol}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[oklch(0.6_0_0)]">Degraded</span>
                <span className="font-mono text-xs text-[oklch(0.55_0.22_30)]">
                  {signal.status === "ok" ? "No" : "Yes"}
                </span>
              </div>
            </div>
          ) : (
            <p className="font-mono text-sm text-[oklch(0.38_0_0)] py-4">
              No analysis runs recorded.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
