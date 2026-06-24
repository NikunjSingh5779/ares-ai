"use client";

import { useEffect, useState } from "react";
import { RefreshCw, BookOpen } from "lucide-react";
import { getJournalHistory, getMemory } from "@/lib/api";
import type { JournalHistoryEntry } from "@/types/api";

interface MemoryEntry {
  relevant_memories: Array<{
    type?: string;
    content?: string;
    importance?: number;
    metadata?: Record<string, unknown>;
  }>;
  consolidated: boolean;
  rationale: string;
}

export default function JournalPage() {
  const [history, setHistory] = useState<JournalHistoryEntry[]>([]);
  const [memory, setMemory] = useState<MemoryEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [h, m] = await Promise.all([
        getJournalHistory().catch(() => []),
        getMemory().catch(() => null),
      ]);
      setHistory(h);
      setMemory(m);
    } catch {
      setError("Could not fetch journal data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">
            Journal
          </h1>
          <p className="text-label mt-1">
            Post-Trade Journal & Memory
          </p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="btn-primary !py-2 !px-3 !text-xs !font-mono disabled:opacity-50"
        >
          <BookOpen size={12} />
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3">
          <p className="font-mono text-xs text-[#ef4444]">{error}</p>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <RefreshCw size={20} className="animate-spin text-[#6366f1]" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Journal History */}
          <div className="card-glass flex flex-col gap-4">
            <p className="text-label">
              Journal History ({history.length})
            </p>
            {history.length > 0 ? (
              <div className="space-y-4">
                {history.map((entry) => (
                  <div key={entry.id} className="rounded-lg border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.02)] p-4">
                    <div className="flex items-center justify-between mb-3">
                      <span className="font-mono text-xs text-[#a1a1aa]">{new Date(entry.created_at).toLocaleString()}</span>
                      <span className="font-mono text-[10px] text-[#52525b]">
                        ID: {entry.id.slice(0, 8)}
                      </span>
                    </div>

                    <div className="space-y-3">
                      <div>
                        <p className="text-label mb-1.5 text-[10px]">
                          Mistakes ({entry.mistakes_detected?.length || 0})
                        </p>
                        {entry.mistakes_detected && entry.mistakes_detected.length > 0 ? (
                          <ul className="space-y-1">
                            {entry.mistakes_detected.map((m, i) => (
                              <li
                                key={i}
                                className="rounded-md bg-[rgba(239,68,68,0.08)] border border-[rgba(239,68,68,0.15)] px-2 py-1.5 font-mono text-[11px] text-[#ef4444]"
                              >
                                • {m}
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="font-mono text-[11px] text-[#52525b]">None</p>
                        )}
                      </div>

                      <div>
                        <p className="text-label mb-1.5 text-[10px]">
                          Lessons ({entry.lessons_learned?.length || 0})
                        </p>
                        {entry.lessons_learned && entry.lessons_learned.length > 0 ? (
                          <ul className="space-y-1">
                            {entry.lessons_learned.map((l, i) => (
                              <li
                                key={i}
                                className="rounded-md bg-[rgba(34,197,94,0.08)] border border-[rgba(34,197,94,0.15)] px-2 py-1.5 font-mono text-[11px] text-[#22c55e]"
                              >
                                • {l}
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="font-mono text-[11px] text-[#52525b]">None</p>
                        )}
                      </div>

                      <div className="border-t border-[rgba(255,255,255,0.06)] pt-2">
                        <p className="font-mono text-xs text-[#71717a] leading-relaxed">
                          {entry.content}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <p className="font-mono text-sm text-[#52525b] py-4">
                No journal entries yet. Run a pipeline to generate journal data.
              </p>
            )}
          </div>

          {/* Memory Records */}
          <div className="card-glass">
            <p className="text-label mb-4">
              Memory Records
            </p>
            {memory ? (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-[#a1a1aa]">Consolidated</span>
                  <span
                    className={`font-mono text-xs font-medium ${
                      memory.consolidated ? "text-[#22c55e]" : "text-[#ef4444]"
                    }`}
                  >
                    {memory.consolidated ? "Yes" : "No"}
                  </span>
                </div>

                <div>
                  <p className="text-label mb-2">
                    Records ({memory.relevant_memories.length})
                  </p>
                  {memory.relevant_memories.length > 0 ? (
                    <div className="space-y-2">
                      {memory.relevant_memories.map((mem, i) => (
                        <div
                          key={i}
                          className="rounded-lg border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.02)] p-3"
                        >
                          <div className="flex items-center justify-between mb-1.5">
                            <span className="font-mono text-xs text-[#a1a1aa]">
                              {mem.type || "unknown"}
                            </span>
                            <span className="font-mono text-[10px] text-[#52525b]">
                              importance: {mem.importance ?? "N/A"}
                            </span>
                          </div>
                          <p className="font-mono text-xs text-[#e4e4e7] leading-relaxed">
                            {mem.content}
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="font-mono text-xs text-[#52525b]">No memory records</p>
                  )}
                </div>
              </div>
            ) : (
              <p className="font-mono text-sm text-[#52525b] py-4">
                No memory records yet.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
