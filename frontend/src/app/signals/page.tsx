"use client";

import { useEffect, useState } from "react";
import { TrendingUp, RefreshCw } from "lucide-react";
import { DataTable, type Column } from "@/components/DataTable";
import { getSignalHistory } from "@/lib/api";
import type { SignalHistoryEntry } from "@/types/api";

export default function SignalsPage() {
  const [history, setHistory] = useState<SignalHistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadHistory() {
    setLoading(true);
    setError(null);
    try {
      const result = await getSignalHistory();
      setHistory(result);
    } catch {
      setError("Could not fetch signal history");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadHistory();
  }, []);

  const columns: Column<SignalHistoryEntry>[] = [
    { 
      key: "created_at", 
      label: "Date",
      render: (s) => new Date(s.created_at).toLocaleString()
    },
    { key: "symbol", label: "Symbol", className: "font-medium" },
    {
      key: "direction",
      label: "Direction",
      render: (s) => (
        <span
          className={`font-semibold ${
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
      key: "market_analyst_confidence", 
      label: "MA Conf.",
      render: (s) => `${s.market_analyst_confidence.toFixed(0)}%`
    },
    { 
      key: "quant_confidence", 
      label: "Quant Conf.",
      render: (s) => `${s.quant_confidence.toFixed(0)}%`
    },
    { 
      key: "composite_confidence", 
      label: "Overall Conf.",
      render: (s) => <span className="font-bold text-white">{s.composite_confidence.toFixed(0)}%</span>
    },
    {
      key: "is_executed",
      label: "Executed",
      render: (s) => (
        <span
          className={`px-2 py-0.5 rounded text-[10px] font-bold tracking-wider uppercase ${
            s.is_executed
              ? "bg-[rgba(34,197,94,0.1)] text-[#22c55e] border border-[rgba(34,197,94,0.2)]"
              : "bg-[rgba(239,68,68,0.1)] text-[#ef4444] border border-[rgba(239,68,68,0.2)]"
          }`}
        >
          {s.is_executed ? "YES" : "NO"}
        </span>
      )
    },
  ];

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">
            Signals
          </h1>
          <p className="text-label mt-1">
            Historical Buy/Sell Signals
          </p>
        </div>
        <button
          onClick={loadHistory}
          disabled={loading}
          className="btn-primary !py-2 !px-3 !text-xs !font-mono disabled:opacity-50"
        >
          <TrendingUp size={12} />
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3">
          <p className="font-mono text-xs text-[#ef4444]">{error}</p>
        </div>
      )}

      <div className="card-glass p-0 overflow-hidden">
        {loading && history.length === 0 ? (
          <div className="flex justify-center py-8">
            <RefreshCw size={16} className="animate-spin text-[#6366f1]" />
          </div>
        ) : (
          <DataTable
            columns={columns}
            data={history}
            emptyMessage="No historical signals recorded yet. Run a pipeline to generate signals."
          />
        )}
      </div>
    </div>
  );
}
