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
          <h1 className="font-mono text-xl font-semibold text-[oklch(0.92_0_0)]">
            Agents
          </h1>
          <p className="font-mono text-xs text-[oklch(0.6_0_0)]">
            Pipeline Monitor & Agent Outputs
          </p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="flex items-center gap-1.5 rounded-md bg-[oklch(0.62_0.19_145)] px-3 py-1.5 font-mono text-xs font-medium text-black transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          <Cpu size={12} />
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="rounded-lg border border-[oklch(0.25_0.08_30)] bg-[oklch(0.25_0.08_30)] px-4 py-2">
          <p className="font-mono text-xs text-[oklch(0.55_0.22_30)]">{error}</p>
        </div>
      )}

      {/* Pipeline Flow */}
      <PipelineFlow status={pipelineStatus} />

      {/* Summary */}
      {status && (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <div className="rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.18_0.01_145)] p-4">
            <p className="mb-1 font-mono text-xs text-[oklch(0.6_0_0)]">Completed</p>
            <p className="font-mono text-2xl font-semibold text-[oklch(0.62_0.19_145)]">
              {pipelineStatus?.completed_nodes.length ?? 0}
            </p>
          </div>
          <div className="rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.18_0.01_145)] p-4">
            <p className="mb-1 font-mono text-xs text-[oklch(0.6_0_0)]">Failed</p>
            <p className="font-mono text-2xl font-semibold text-[oklch(0.55_0.22_30)]">
              {pipelineStatus?.failed_nodes.length ?? 0}
            </p>
          </div>
          <div className="rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.18_0.01_145)] p-4">
            <p className="mb-1 font-mono text-xs text-[oklch(0.6_0_0)]">Latency</p>
            <p className="font-mono text-2xl font-semibold text-[oklch(0.92_0_0)]">
              {status.total_latency_ms}ms
            </p>
          </div>
        </div>
      )}

      {/* Agent Output List */}
      <div className="rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.13_0_0)]">
        <div className="border-b border-[oklch(0.25_0_0)] p-3">
          <p className="font-mono text-xs font-medium text-[oklch(0.6_0_0)] uppercase tracking-wider">
            Agent Outputs
          </p>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-8">
            <RefreshCw size={16} className="animate-spin text-[oklch(0.6_0_0)]" />
          </div>
        ) : (
          <div className="divide-y divide-[oklch(0.25_0_0)]">
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
                    className="flex w-full items-center justify-between px-4 py-3 text-left transition-colors hover:bg-[oklch(0.22_0.01_145)]"
                  >
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-sm text-[oklch(0.92_0_0)]">
                        {agentLabels[agent]}
                      </span>
                      <StatusBadge status={agentStatus} />
                    </div>
                    <span className="font-mono text-xs text-[oklch(0.38_0_0)]">
                      {output ? "Has output" : "No output"}
                    </span>
                  </button>

                  {isExpanded && output && (
                    <div className="border-t border-[oklch(0.25_0_0)] bg-[oklch(0.18_0.01_145)] px-4 py-3">
                      <pre className="overflow-x-auto font-mono text-xs text-[oklch(0.88_0_0)] leading-relaxed">
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
