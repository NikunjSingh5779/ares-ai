"use client";

import { useEffect, useState } from "react";
import { RefreshCw, Database, Brain, Star, BookOpen } from "lucide-react";
import { getMemory } from "@/lib/api";

interface MemoryView {
  relevant_memories: Array<{
    type: string;
    content: string;
    importance: number;
    metadata?: Record<string, unknown>;
  }>;
  consolidated: boolean;
  rationale: string;
}

export default function MemoryPage() {
  const [memory, setMemory] = useState<MemoryView | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expandedMemory, setExpandedMemory] = useState<number | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const m = await getMemory();
      setMemory(m as unknown as MemoryView);
    } catch {
      setError("Could not fetch memory data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  const getTypeColor = (type: string) => {
    switch (type) {
      case "trade": return "text-[#22c55e] border-[#22c55e] bg-[rgba(34,197,94,0.08)]";
      case "agent_output": return "text-[#6366f1] border-[#6366f1] bg-[rgba(99,102,241,0.08)]";
      case "user_preference": return "text-[#f59e0b] border-[#f59e0b] bg-[rgba(245,158,11,0.08)]";
      default: return "text-[#a1a1aa] border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.04)]";
    }
  };

  const getImportanceBadge = (importance: number) => {
    if (importance >= 8) return { label: "HIGH", color: "text-[#ef4444]" };
    if (importance >= 5) return { label: "MEDIUM", color: "text-[#f59e0b]" };
    return { label: "LOW", color: "text-[#52525b]" };
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">Memory Viewer</h1>
          <p className="text-label mt-1">Agent Memory & Knowledge Store</p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="btn-primary !py-2 !px-3 !text-xs !font-mono disabled:opacity-50"
        >
          <RefreshCw size={12} />
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3">
          <p className="font-mono text-xs text-[#ef4444]">{error}</p>
        </div>
      )}

      {/* Status */}
      {memory && (
        <div className={`rounded-xl border p-4 ${
          memory.consolidated
            ? "border-[rgba(34,197,94,0.2)] bg-[rgba(34,197,94,0.06)]"
            : "border-[rgba(245,158,11,0.2)] bg-[rgba(245,158,11,0.06)]"
        }`}>
          <div className="flex items-center gap-3">
            <Database size={20} className={memory.consolidated ? "text-[#22c55e]" : "text-[#f59e0b]"} />
            <div>
              <p className={`font-sans text-sm font-semibold ${
                memory.consolidated ? "text-[#22c55e]" : "text-[#f59e0b]"
              }`}>
                Memory {memory.consolidated ? "Consolidated" : "Pending Consolidation"}
              </p>
              <p className="font-mono text-xs text-[#a1a1aa]">
                {memory.relevant_memories.length} relevant memories
              </p>
            </div>
          </div>
        </div>
      )}

      {loading && !memory && (
        <div className="flex items-center justify-center py-12">
          <RefreshCw size={16} className="animate-spin text-[#6366f1]" />
        </div>
      )}

      {/* Memory List */}
      {memory && (
        <div className="space-y-3">
          {memory.relevant_memories.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <Brain size={32} className="text-[#52525b] mb-3" />
              <p className="font-mono text-xs text-[#52525b]">No memories stored yet</p>
              <p className="font-mono text-[10px] text-[#3f3f46] mt-1">
                Memories are created after pipeline runs
              </p>
            </div>
          )}

          {memory.relevant_memories.map((mem, i) => {
            const badge = getImportanceBadge(mem.importance);
            const isExpanded = expandedMemory === i;

            return (
              <div
                key={i}
                className="card-glass overflow-hidden"
              >
                <button
                  onClick={() => setExpandedMemory(isExpanded ? null : i)}
                  className="flex w-full items-start justify-between gap-4 text-left"
                >
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-2">
                      <span className={`rounded-full border px-2 py-0.5 font-mono text-[10px] ${getTypeColor(mem.type)}`}>
                        {mem.type.replace("_", " ")}
                      </span>
                      <span className={`font-mono text-[10px] font-semibold ${badge.color}`}>
                        {badge.label}
                      </span>
                      <div className="flex items-center gap-0.5 ml-1">
                        {Array.from({ length: Math.min(5, Math.ceil(mem.importance / 2)) }).map((_, si) => (
                          <Star key={si} size={8} className="fill-[#f59e0b] text-[#f59e0b]" />
                        ))}
                      </div>
                    </div>
                    <p className="font-mono text-xs text-[#e4e4e7] leading-relaxed line-clamp-2">
                      {mem.content}
                    </p>
                  </div>
                  <span className="font-mono text-[10px] text-[#52525b] shrink-0 mt-1">
                    {isExpanded ? "▲" : "▼"}
                  </span>
                </button>

                {isExpanded && mem.metadata && Object.keys(mem.metadata).length > 0 && (
                  <div className="mt-3 border-t border-[rgba(255,255,255,0.06)] pt-3">
                    <p className="text-label text-[10px] mb-2">Metadata</p>
                    <pre className="overflow-x-auto rounded-lg bg-[rgba(0,0,0,0.2)] p-3 font-mono text-[10px] text-[#a1a1aa] leading-relaxed">
                      {JSON.stringify(mem.metadata, null, 2)}
                    </pre>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Rationale */}
      {memory?.rationale && (
        <div className="card-glass">
          <div className="flex items-center gap-2 mb-3">
            <BookOpen size={14} className="text-[#6366f1]" />
            <p className="text-label">Memory Rationale</p>
          </div>
          <p className="font-mono text-xs text-[#a1a1aa] leading-relaxed">
            {memory.rationale}
          </p>
        </div>
      )}
    </div>
  );
}
