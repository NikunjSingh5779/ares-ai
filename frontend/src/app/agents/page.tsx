"use client";

import { useEffect, useState } from "react";
import { RefreshCw, Cpu } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import { PipelineFlow } from "@/components/PipelineFlow";
import { getAgentStatus, analyze } from "@/lib/api";
import type { AgentStatusResponse, AgentState } from "@/types/api";

const AGENT_NAMES = [
  "market_analyst",
  "quant",
  "consensus",
  "risk",
  "execution",
  "journal",
  "reflection",
  "memory",
];

const agentLabels: Record<string, string> = {
  market_analyst: "Market Analyst",
  quant: "Quant",
  consensus: "Consensus",
  risk: "Risk",
  execution: "Execution",
  journal: "Journal",
  reflection: "Reflection",
  memory: "Memory",
};

export default function AgentsPage() {
  const [status, setStatus] = useState<AgentStatusResponse | null>(null);
  const [state, setState] = useState<AgentState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const s = await getAgentStatus().catch(() => null);
      setStatus(s);

      // Run a quick analysis to get full state if none exists
      if (!s?.has_run) {
        const result = await analyze("BTC-USD", "Agent status check").catch(() => null);
        setState(result);
        const s2 = await getAgentStatus().catch(() => null);
        setStatus(s2);
      } else {
        setState(null);
      }
    } catch {
      setError("Could not fetch agent data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  const pipelineStatus = status?.pipeline_status ?? state?.pipeline_status ?? null;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">
            Agents
          </h1>
          <p className="text-label mt-1">
            Pipeline Monitor & Agent Outputs
          </p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="btn-primary !py-2 !px-3 !text-xs !font-mono disabled:opacity-50"
        >
          <Cpu size={12} />
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3">
          <p className="font-mono text-xs text-[#ef4444]">{error}</p>
        </div>
      )}

      {/* Pipeline Flow */}
      <PipelineFlow status={pipelineStatus} />

      {/* Summary */}
      {status && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="card-glass">
            <p className="text-label mb-1">Completed</p>
            <p className="font-sans text-2xl font-bold text-[#22c55e]">
              {pipelineStatus?.completed_nodes.length ?? 0}
            </p>
          </div>
          <div className="card-glass">
            <p className="text-label mb-1">Failed</p>
            <p className="font-sans text-2xl font-bold text-[#ef4444]">
              {pipelineStatus?.failed_nodes.length ?? 0}
            </p>
          </div>
          <div className="card-glass">
            <p className="text-label mb-1">Latency</p>
            <p className="font-sans text-2xl font-bold text-white">
              {status.total_latency_ms}ms
            </p>
          </div>
        </div>
      )}

      {/* Agent Output List */}
      <div className="card-glass !p-0 overflow-hidden">
        <div className="border-b border-[rgba(255,255,255,0.06)] px-5 py-4">
          <p className="text-label">
            Agent Outputs
          </p>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <RefreshCw size={16} className="animate-spin text-[#6366f1]" />
          </div>
        ) : (
          <div className="divide-y divide-[rgba(255,255,255,0.04)]">
            {AGENT_NAMES.map((agent) => {
              const output = state?.[agent as keyof AgentState] as Record<string, unknown> | null | undefined;
              const isExpanded = selectedAgent === agent;
              const agentStatus = pipelineStatus?.completed_nodes.includes(agent)
                ? ("completed" as const)
                : pipelineStatus?.failed_nodes.includes(agent)
                  ? ("failed" as const)
                  : pipelineStatus?.skipped_nodes.includes(agent)
                    ? ("skipped" as const)
                    : ("pending" as const);

              return (
                <div key={agent}>
                  <button
                    onClick={() => setSelectedAgent(isExpanded ? null : agent)}
                    className="flex w-full items-center justify-between px-5 py-3.5 text-left transition-colors hover:bg-[rgba(255,255,255,0.03)]"
                  >
                    <div className="flex items-center gap-3">
                      <span className="font-sans text-sm font-medium text-white">
                        {agentLabels[agent]}
                      </span>
                      <StatusBadge status={agentStatus} />
                    </div>
                    <span className="font-mono text-xs text-[#52525b]">
                      {output ? "Has output" : "No output"}
                    </span>
                  </button>

                  {isExpanded && output && (
                    <div className="border-t border-[rgba(255,255,255,0.04)] bg-[rgba(255,255,255,0.02)] px-5 py-4">
                      <pre className="overflow-x-auto font-mono text-xs text-[#e4e4e7] leading-relaxed">
                        {JSON.stringify(output, null, 2)}
                      </pre>
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
