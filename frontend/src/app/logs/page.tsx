"use client";

import { useEffect, useState } from "react";
import { RefreshCw, AlertTriangle, FileText, Search } from "lucide-react";
import { getAgentStatus } from "@/lib/api";
import type { AgentStatusResponse } from "@/types/api";

interface LogEntry {
  timestamp: string;
  level: "info" | "warn" | "error";
  source: string;
  message: string;
}

export default function LogsPage() {
  const [agentStatus, setAgentStatus] = useState<AgentStatusResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState<string>("all");
  const [search, setSearch] = useState("");

  async function loadData() {
    setLoading(true);
    try {
      const s = await getAgentStatus().catch(() => null);
      setAgentStatus(s);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  // Build log entries from agent status data
  const logs: LogEntry[] = [];
  if (agentStatus?.errors && agentStatus.errors.length > 0) {
    agentStatus.errors.forEach((err) => {
      logs.push({
        timestamp: new Date().toISOString(),
        level: "error",
        source: err.agent,
        message: err.error,
      });
    });
  }

  if (agentStatus?.model_chain_used) {
    Object.entries(agentStatus.model_chain_used).forEach(([agent, models]) => {
      if (models.length > 1) {
        logs.push({
          timestamp: new Date().toISOString(),
          level: "warn",
          source: agent,
          message: `Used fallback chain: ${models.join(" → ")}`,
        });
      }
    });
  }

  if (agentStatus?.degraded) {
    logs.push({
      timestamp: new Date().toISOString(),
      level: "warn",
      source: "system",
      message: "System running in degraded mode — one or more models unavailable",
    });
  }

  // Add sample info entries when there's pipeline activity
  if (agentStatus?.pipeline_status?.completed_nodes) {
    agentStatus.pipeline_status.completed_nodes.forEach((node) => {
      logs.push({
        timestamp: agentStatus.pipeline_status.end_time || new Date().toISOString(),
        level: "info",
        source: node,
        message: "Pipeline node completed successfully",
      });
    });
  }

  if (agentStatus?.pipeline_status?.failed_nodes) {
    agentStatus.pipeline_status.failed_nodes.forEach((node) => {
      logs.push({
        timestamp: agentStatus.pipeline_status.end_time || new Date().toISOString(),
        level: "error",
        source: node,
        message: "Pipeline node failed",
      });
    });
  }

  // Sort by timestamp descending
  logs.sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime());

  const filteredLogs = logs.filter((log) => {
    if (filter !== "all" && log.level !== filter) return false;
    if (search && !log.message.toLowerCase().includes(search.toLowerCase()) && !log.source.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">System Logs</h1>
          <p className="text-label mt-1">Agent Pipeline & System Events</p>
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

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1.5 rounded-lg border border-[rgba(255,255,255,0.08)] p-1">
          {["all", "info", "warn", "error"].map((level) => (
            <button
              key={level}
              onClick={() => setFilter(level)}
              className={`rounded-md px-3 py-1.5 font-mono text-xs transition-all ${
                filter === level
                  ? "bg-[#6366f1] text-black font-semibold"
                  : "text-[#a1a1aa] hover:text-white"
              }`}
            >
              {level.toUpperCase()}
            </button>
          ))}
        </div>
        <div className="relative flex-1 max-w-xs">
          <Search size={12} className="absolute left-3 top-1/2 -translate-y-1/2 text-[#52525b]" />
          <input
            type="text"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search logs..."
            className="w-full rounded-lg border border-[rgba(255,255,255,0.08)] bg-[rgba(255,255,255,0.03)] py-1.5 pl-8 pr-3 font-mono text-xs text-white placeholder-[#52525b] outline-none transition-colors focus:border-[#6366f1]"
          />
        </div>
      </div>

      {/* Log Output */}
      <div className="card-glass !p-0 overflow-hidden">
        <div className="border-b border-[rgba(255,255,255,0.06)] px-5 py-3">
          <div className="flex items-center justify-between">
            <p className="text-label">Event Log</p>
            <span className="font-mono text-xs text-[#52525b]">
              {filteredLogs.length} entries
            </span>
          </div>
        </div>

        <div className="max-h-[600px] overflow-y-auto">
          {loading && (
            <div className="flex items-center justify-center py-12">
              <RefreshCw size={16} className="animate-spin text-[#6366f1]" />
            </div>
          )}

          {!loading && filteredLogs.length === 0 && (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <FileText size={24} className="text-[#52525b] mb-3" />
              <p className="font-mono text-xs text-[#52525b]">No log entries</p>
              <p className="font-mono text-[10px] text-[#3f3f46] mt-1">
                {search ? "Try a different search term" : "Run an analysis to generate log entries"}
              </p>
            </div>
          )}

          {filteredLogs.length > 0 && (
            <div className="divide-y divide-[rgba(255,255,255,0.04)]">
              {filteredLogs.map((log, i) => (
                <div key={i} className="flex items-start gap-3 px-5 py-2.5 hover:bg-[rgba(255,255,255,0.02)]">
                  <div className="mt-0.5 shrink-0">
                    {log.level === "error" && (
                      <AlertTriangle size={12} className="text-[#ef4444]" />
                    )}
                    {log.level === "warn" && (
                      <AlertTriangle size={12} className="text-[#f59e0b]" />
                    )}
                    {log.level === "info" && (
                      <div className="h-3 w-3 rounded-full bg-[rgba(99,102,241,0.2)] flex items-center justify-center">
                        <div className="h-1.5 w-1.5 rounded-full bg-[#6366f1]" />
                      </div>
                    )}
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <span className={`font-mono text-[10px] font-semibold uppercase ${
                        log.level === "error" ? "text-[#ef4444]" :
                        log.level === "warn" ? "text-[#f59e0b]" :
                        "text-[#6366f1]"
                      }`}>
                        {log.level}
                      </span>
                      <span className="font-mono text-[10px] text-[#52525b]">
                        [{log.source}]
                      </span>
                      <span className="font-mono text-[10px] text-[#3f3f46] ml-auto">
                        {new Date(log.timestamp).toLocaleTimeString()}
                      </span>
                    </div>
                    <p className="mt-0.5 font-mono text-xs text-[#e4e4e7] break-words">
                      {log.message}
                    </p>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Summary */}
      {logs.length > 0 && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="card-glass">
            <p className="text-label mb-1">Errors</p>
            <p className="font-sans text-2xl font-bold text-[#ef4444]">
              {logs.filter((l) => l.level === "error").length}
            </p>
          </div>
          <div className="card-glass">
            <p className="text-label mb-1">Warnings</p>
            <p className="font-sans text-2xl font-bold text-[#f59e0b]">
              {logs.filter((l) => l.level === "warn").length}
            </p>
          </div>
          <div className="card-glass">
            <p className="text-label mb-1">Info</p>
            <p className="font-sans text-2xl font-bold text-white">
              {logs.filter((l) => l.level === "info").length}
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
