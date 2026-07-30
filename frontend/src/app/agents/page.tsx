"use client";

import { useEffect, useState } from "react";
import { RefreshCw, Cpu, AlertTriangle } from "lucide-react";
import { StatusBadge } from "@/components/StatusBadge";
import { PipelineFlow } from "@/components/PipelineFlow";
import { PriceTicker } from "@/components/PriceTicker";
import { usePipelinePolling } from "@/lib/usePipelinePolling";
import type { AgentState } from "@/types/api";

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
  const [loading, setLoading] = useState(true);
  const [selectedAgent, setSelectedAgent] = useState<string | null>(null);

  // Pipeline hook owns the full lifecycle internally.
  const { status, running, error, timedOut, runAnalysis } = usePipelinePolling();

  // Trigger a fresh analysis on mount so the pipeline has completed state.
  useEffect(() => {
    if (!status?.has_run && !running) {
      runAnalysis("BTC-USD", "Agent status check").finally(() => setLoading(false));
    } else {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pipelineStatus = status?.pipeline_status ?? null;

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
        <div className="flex items-center gap-4">
          <PriceTicker symbol="BTCUSDT" />
          <button
            onClick={() => runAnalysis("BTC-USD", "Agent status check")}
            disabled={running || loading}
            className="btn-primary !py-2 !px-3 !text-xs !font-mono disabled:opacity-50"
          >
            <Cpu size={12} />
            {loading ? "Loading..." : "Refresh"}
          </button>
        </div>
      </div>

      {/* Error */}
      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3">
          <AlertTriangle size={14} className="text-[#ef4444]" />
          <span className="font-mono text-xs text-[#ef4444]">
            {error}
          </span>
        </div>
      )}
      {timedOut && (
        <div className="flex items-center gap-2 rounded-xl border border-[rgba(255,159,28,0.2)] bg-[rgba(255,159,28,0.08)] px-4 py-3">
          <AlertTriangle size={14} className="text-[#ff9f1c]" />
          <span className="font-mono text-xs text-[#ff9f1c]">
            Pipeline timed out after 60 seconds.
          </span>
        </div>
      )}

      {/* Pipeline Flow */}
      <PipelineFlow status={pipelineStatus} />

      {/* Agent list */}
      {loading ? (
        <div className="flex items-center justify-center py-8">
          <RefreshCw size={16} className="animate-spin text-[#6366f1]" />
        </div>
      ) : (
        <div className="divide-y divide-[rgba(255,255,255,0.04)]">
          {AGENT_NAMES.map((agent) => {
            const output = status?.[agent as keyof typeof status] as Record<string, unknown> | null | undefined;
            const isExpanded = selectedAgent === agent;
            const agentStatus = pipelineStatus?.completed_nodes.includes(agent)
              ? ("completed" as const)
              : pipelineStatus?.failed_nodes.includes(agent)
                ? ("failed" as const)
                : pipelineStatus?.skipped_nodes.includes(agent)
                  ? ("skipped" as const)
                  : ("pending" as const);

            return (
              <div key={agent} className="py-4">
                <button
                  onClick={() => setSelectedAgent(isExpanded ? null : agent)}
                  className="flex w-full items-center justify-between text-left"
                >
                  <div className="flex items-center gap-3">
                    <StatusBadge status={agentStatus} />
                    <span className="font-mono text-sm font-medium text-white">
                      {agentLabels[agent] ?? agent}
                    </span>
                  </div>
                  <span className="font-mono text-xs text-[#52525b] tracking-wider">
                    {isExpanded ? "▲" : "▼"}
                  </span>
                </button>

                {isExpanded && output && (
                  <div className="mt-3 overflow-x-auto rounded-lg border border-[rgba(255,255,255,0.06)] bg-[rgba(255,255,255,0.02)] p-4">
                    <pre className="font-mono text-[11px] text-[#a1a1aa] leading-relaxed whitespace-pre-wrap">
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
  );
}
