"use client";

import { useEffect, useState } from "react";
import { TrendingUp, RefreshCw } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import { getSignal } from "@/lib/api";
import type { SignalResponse } from "@/types/api";

export default function SignalsPage() {
  const [signal, setSignal] = useState<SignalResponse | null>(null);
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
          <h1 className="text-heading text-xl text-white">
            Signals
          </h1>
          <p className="text-label mt-1">
            Agent Pipeline Signal History
          </p>
        </div>
        <button
          onClick={loadSignal}
          disabled={loading}
          className="btn-primary !py-2 !px-3 !text-xs !font-mono disabled:opacity-50"
        >
          <TrendingUp size={12} />
          {loading ? "Loading..." : "Run Signal"}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3">
          <p className="font-mono text-xs text-[#ef4444]">{error}</p>
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* Signal Status Card */}
        <div className="card-glass">
          <p className="text-label mb-4">
            Signal Status
          </p>
          {signal ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[#a1a1aa]">Status</span>
                <StatusBadge status={signal.approved ? "approved" : "rejected"} />
              </div>
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[#a1a1aa]">Direction</span>
                <span
                  className={`font-mono text-sm font-bold ${
                    signal.direction === "long"
                      ? "text-[#22c55e]"
                      : signal.direction === "short"
                        ? "text-[#ef4444]"
                        : "text-[#a1a1aa]"
                  }`}
                >
                  {signal.direction.toUpperCase()}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[#a1a1aa]">Confidence</span>
                <span className="font-mono text-sm font-bold text-white">
                  {signal.confidence.toFixed(0)}%
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[#a1a1aa]">Executed</span>
                <StatusBadge status={signal.executed ? "ok" : "skipped"} label={signal.executed ? "Yes" : "No"} />
              </div>
              {signal.rationale && (
                <>
                  <hr className="border-[rgba(255,255,255,0.06)]" />
                  <p className="font-mono text-xs text-[#71717a] leading-relaxed">
                    {signal.rationale}
                  </p>
                </>
              )}
            </div>
          ) : loading ? (
            <div className="flex justify-center py-8">
              <RefreshCw size={16} className="animate-spin text-[#6366f1]" />
            </div>
          ) : (
            <p className="font-mono text-sm text-[#52525b] py-4">
              No signal data yet. Run a signal to see results.
            </p>
          )}
        </div>

        {/* Pipeline Status */}
        <div className="card-glass">
          <p className="text-label mb-4">
            Pipeline Status
          </p>
          {signal?.pipeline_status ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[#a1a1aa]">Completed</span>
                <span className="font-mono text-sm font-bold text-[#22c55e]">
                  {signal.pipeline_status.completed_nodes.length}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[#a1a1aa]">Failed</span>
                <span className="font-mono text-sm font-bold text-[#ef4444]">
                  {signal.pipeline_status.failed_nodes.length}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[#a1a1aa]">Skipped</span>
                <span className="font-mono text-sm font-bold text-[#52525b]">
                  {signal.pipeline_status.skipped_nodes.length}
                </span>
              </div>
              {signal.errors.length > 0 && (
                <div className="mt-2 space-y-1">
                  {signal.errors.map((err, i) => (
                    <div
                      key={i}
                      className="rounded-lg bg-[rgba(239,68,68,0.08)] border border-[rgba(239,68,68,0.15)] px-2 py-1.5 font-mono text-xs text-[#ef4444]"
                    >
                      {err.agent}: {err.error}
                    </div>
                  ))}
                </div>
              )}
            </div>
          ) : (
            <p className="font-mono text-sm text-[#52525b] py-4">
              No pipeline has run yet.
            </p>
          )}
        </div>

        {/* Agent Outputs */}
        <div className="card-glass">
          <p className="text-label mb-4">
            Latest Run
          </p>
          {signal ? (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[#a1a1aa]">Symbol</span>
                <span className="font-mono text-sm font-medium text-white">{signal.symbol}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="font-mono text-xs text-[#a1a1aa]">Degraded</span>
                <span className={`font-mono text-sm font-medium ${signal.status === "ok" ? "text-[#22c55e]" : "text-[#ef4444]"}`}>
                  {signal.status === "ok" ? "No" : "Yes"}
                </span>
              </div>
            </div>
          ) : (
            <p className="font-mono text-sm text-[#52525b] py-4">
              No analysis runs recorded.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
