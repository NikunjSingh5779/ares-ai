"use client";

import { useEffect, useState } from "react";
import { RefreshCw, BookOpen } from "lucide-react";
import { getJournal, getMemory, analyze } from "@/lib/api";

interface JournalEntry {
  entry_id: string | null;
  mistakes: string[];
  lessons: string[];
  rationale: string;
}

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
  const [journal, setJournal] = useState<JournalEntry | null>(null);
  const [memory, setMemory] = useState<MemoryEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      // Run analysis first to generate journal/memory data
      await analyze("BTC-USD", "Journal check").catch(() => {});
      const [j, m] = await Promise.all([
        getJournal().catch(() => null),
        getMemory().catch(() => null),
      ]);
      setJournal(j);
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
          <h1 className="font-mono text-xl font-semibold text-[oklch(0.92_0_0)]">
            Journal
          </h1>
          <p className="font-mono text-xs text-[oklch(0.6_0_0)]">
            Post-Trade Journal & Memory
          </p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-md bg-[oklch(0.62_0.19_145)] px-3 py-1.5 font-mono text-xs font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          <BookOpen size={12} />
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-[oklch(0.25_0.08_30)] bg-[oklch(0.25_0.08_30)] px-4 py-2">
          <p className="font-mono text-xs text-[oklch(0.55_0.22_30)]">{error}</p>
        </div>
      )}

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <RefreshCw size={20} className="animate-spin text-[oklch(0.6_0_0)]" />
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Journal Entry */}
          <div className="rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.18_0.01_145)] p-4">
            <p className="mb-3 font-mono text-xs font-medium text-[oklch(0.6_0_0)] uppercase tracking-wider">
              Journal Entry
            </p>
            {journal ? (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-[oklch(0.6_0_0)]">Entry ID</span>
                  <span className="font-mono text-xs text-[oklch(0.92_0_0)]">
                    {journal.entry_id?.slice(0, 8) || "N/A"}...
                  </span>
                </div>

                <div>
                  <p className="mb-2 font-mono text-xs font-medium text-[oklch(0.6_0_0)]">
                    Mistakes ({journal.mistakes.length})
                  </p>
                  {journal.mistakes.length > 0 ? (
                    <ul className="space-y-1">
                      {journal.mistakes.map((m, i) => (
                        <li
                          key={i}
                          className="rounded bg-[oklch(0.25_0.08_30)] px-2 py-1 font-mono text-xs text-[oklch(0.55_0.22_30)]"
                        >
                          • {m}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="font-mono text-xs text-[oklch(0.38_0_0)]">No mistakes recorded</p>
                  )}
                </div>

                <div>
                  <p className="mb-2 font-mono text-xs font-medium text-[oklch(0.6_0_0)]">
                    Lessons ({journal.lessons.length})
                  </p>
                  {journal.lessons.length > 0 ? (
                    <ul className="space-y-1">
                      {journal.lessons.map((l, i) => (
                        <li
                          key={i}
                          className="rounded bg-[oklch(0.25_0.08_145)] px-2 py-1 font-mono text-xs text-[oklch(0.62_0.19_145)]"
                        >
                          • {l}
                        </li>
                      ))}
                    </ul>
                  ) : (
                    <p className="font-mono text-xs text-[oklch(0.38_0_0)]">No lessons extracted</p>
                  )}
                </div>

                <div>
                  <p className="mb-1 font-mono text-xs font-medium text-[oklch(0.6_0_0)]">Rationale</p>
                  <p className="font-mono text-xs text-[oklch(0.5_0_0)] leading-relaxed">
                    {journal.rationale}
                  </p>
                </div>
              </div>
            ) : (
              <p className="font-mono text-sm text-[oklch(0.38_0_0)] py-4">
                No journal entries yet. Run a pipeline to generate journal data.
              </p>
            )}
          </div>

          {/* Memory Records */}
          <div className="rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.18_0.01_145)] p-4">
            <p className="mb-3 font-mono text-xs font-medium text-[oklch(0.6_0_0)] uppercase tracking-wider">
              Memory Records
            </p>
            {memory ? (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="font-mono text-xs text-[oklch(0.6_0_0)]">Consolidated</span>
                  <span
                    className={`font-mono text-xs ${
                      memory.consolidated
                        ? "text-[oklch(0.62_0.19_145)]"
                        : "text-[oklch(0.55_0.22_30)]"
                    }`}
                  >
                    {memory.consolidated ? "Yes" : "No"}
                  </span>
                </div>

                <div>
                  <p className="mb-2 font-mono text-xs font-medium text-[oklch(0.6_0_0)]">
                    Records ({memory.relevant_memories.length})
                  </p>
                  {memory.relevant_memories.length > 0 ? (
                    <div className="space-y-2">
                      {memory.relevant_memories.map((mem, i) => (
                        <div
                          key={i}
                          className="rounded border border-[oklch(0.25_0_0)] bg-[oklch(0.13_0_0)] p-3"
                        >
                          <div className="flex items-center justify-between mb-1">
                            <span className="font-mono text-xs text-[oklch(0.6_0_0)]">
                              {mem.type || "unknown"}
                            </span>
                            <span className="font-mono text-xs text-[oklch(0.38_0_0)]">
                              importance: {mem.importance ?? "N/A"}
                            </span>
                          </div>
                          <p className="font-mono text-xs text-[oklch(0.88_0_0)] leading-relaxed">
                            {mem.content}
                          </p>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="font-mono text-xs text-[oklch(0.38_0_0)]">No memory records</p>
                  )}
                </div>
              </div>
            ) : (
              <p className="font-mono text-sm text-[oklch(0.38_0_0)] py-4">
                No memory records yet.
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
