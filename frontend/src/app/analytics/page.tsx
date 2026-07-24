"use client";

import { useEffect, useState } from "react";
import { RefreshCw, BarChart3, TrendingUp, Activity } from "lucide-react";
import { MetricCard } from "@/components/MetricCard";
import { DataTable, type Column } from "@/components/DataTable";
import { getMetrics, getSignalHistory } from "@/lib/api";
import type { MetricsResponse, SignalHistoryEntry } from "@/types/api";

export default function AnalyticsPage() {
  const [metrics, setMetrics] = useState<MetricsResponse | null>(null);
  const [signals, setSignals] = useState<SignalHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [m, s] = await Promise.all([
        getMetrics().catch(() => null),
        getSignalHistory().catch(() => []),
      ]);
      setMetrics(m);
      setSignals(Array.isArray(s) ? s : []);
    } catch {
      setError("Could not fetch analytics data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  const columns: Column<SignalHistoryEntry>[] = [
    { key: "symbol", label: "Symbol" },
    {
      key: "direction",
      label: "Direction",
      render: (s) => (
        <span
          className={`font-mono text-xs font-semibold ${
            s.direction === "long"
              ? "text-[#22c55e]"
              : s.direction === "short"
                ? "text-[#ef4444]"
                : "text-[#a1a1aa]"
          }`}
        >
          {s.direction.toUpperCase()}
        </span>
      ),
    },
    {
      key: "confidence",
      label: "Confidence",
      render: (s) => (
        <span className="font-mono text-xs text-white">{s.confidence.toFixed(1)}%</span>
      ),
    },
    {
      key: "is_consensus",
      label: "Consensus",
      render: (s) => (
        <span
          className={`font-mono text-xs ${
            s.is_consensus ? "text-[#22c55e]" : "text-[#ef4444]"
          }`}
        >
          {s.is_consensus ? "YES" : "NO"}
        </span>
      ),
    },
    {
      key: "is_executed",
      label: "Executed",
      render: (s) => (
        <span
          className={`font-mono text-xs ${
            s.is_executed ? "text-[#22c55e]" : "text-[#52525b]"
          }`}
        >
          {s.is_executed ? "YES" : "NO"}
        </span>
      ),
    },
    { key: "created_at", label: "Timestamp", render: (s) => (
      <span className="font-mono text-xs text-[#a1a1aa]">
        {new Date(s.created_at).toLocaleString()}
      </span>
    )},
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">Analytics</h1>
          <p className="text-label mt-1">System Metrics & Signal History</p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="btn-primary !py-2 !px-3 !text-xs !font-mono disabled:opacity-50"
        >
          <Activity size={12} />
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3">
          <p className="font-mono text-xs text-[#ef4444]">{error}</p>
        </div>
      )}

      {/* Metrics Grid */}
      {metrics && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <MetricCard label="Total Runs" value={metrics.total_runs.toLocaleString()} />
          <MetricCard label="Agent Executions" value={metrics.total_agents_executed.toLocaleString()} />
          <MetricCard label="Total Errors" value={metrics.total_errors.toLocaleString()} change={metrics.total_errors > 0 ? -1 : 0} />
          <MetricCard label="Total Failures" value={metrics.total_failures.toString()} change={metrics.total_failures > 0 ? -1 : 0} />
          <MetricCard
            label="Degraded Mode"
            value={metrics.degraded ? "YES" : "NO"}
          />
          <MetricCard
            label="Total Latency"
            value={`${metrics.total_latency_ms}ms`}
          />
        </div>
      )}

      {loading && !metrics && (
        <div className="flex items-center justify-center py-12">
          <RefreshCw size={16} className="animate-spin text-[#6366f1]" />
        </div>
      )}

      {/* Signal History */}
      <div className="card-glass !p-0 overflow-hidden">
        <div className="border-b border-[rgba(255,255,255,0.06)] px-5 py-4">
          <div className="flex items-center justify-between">
            <p className="text-label">Signal History</p>
            <span className="font-mono text-xs text-[#52525b]">
              {signals.length} signals
            </span>
          </div>
        </div>
        {signals.length > 0 ? (
          <DataTable columns={columns} data={signals} />
        ) : (
          <div className="flex flex-col items-center justify-center py-12 text-center">
            <BarChart3 size={24} className="text-[#52525b] mb-3" />
            <p className="font-mono text-xs text-[#52525b]">No signal data yet</p>
            <p className="font-mono text-[10px] text-[#3f3f46] mt-1">
              Signals appear after running analysis
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
