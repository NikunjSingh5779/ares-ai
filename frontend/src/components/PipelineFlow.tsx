"use client";

import {
  CheckCircle2,
  XCircle,
  SkipForward,
  Play,
  type LucideIcon,
} from "lucide-react";
import type { PipelineStatus } from "@/types/api";

interface PipelineFlowProps {
  status: PipelineStatus | null;
}

const AGENTS = [
  "market_analyst",
  "quant",
  "news",
  "vision",
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
  news: "News",
  vision: "Vision",
  consensus: "Consensus",
  risk: "Risk",
  execution: "Execution",
  journal: "Journal",
  reflection: "Reflection",
  memory: "Memory",
};

type NodeStatus = "completed" | "failed" | "skipped" | "pending";

function getNodeStatus(
  agent: string,
  status: PipelineStatus | null
): NodeStatus {
  if (!status) return "pending";
  if (status.failed_nodes.includes(agent)) return "failed";
  if (status.completed_nodes.includes(agent)) return "completed";
  if (status.skipped_nodes.includes(agent)) return "skipped";
  if (status.current_node === agent) return "completed";
  return "pending";
}

const statusIcons: Record<NodeStatus, LucideIcon> = {
  completed: CheckCircle2,
  failed: XCircle,
  skipped: SkipForward,
  pending: Play,
};

const statusColors: Record<NodeStatus, string> = {
  completed: "text-[#22c55e]",
  failed: "text-[#ef4444]",
  skipped: "text-[#52525b]",
  pending: "text-[#3f3f46]",
};

const statusBg: Record<NodeStatus, string> = {
  completed: "bg-[rgba(34,197,94,0.1)] border-[rgba(34,197,94,0.2)]",
  failed: "bg-[rgba(239,68,68,0.1)] border-[rgba(239,68,68,0.2)]",
  skipped: "bg-[rgba(255,255,255,0.02)] border-[rgba(255,255,255,0.06)]",
  pending: "bg-[rgba(255,255,255,0.02)] border-[rgba(255,255,255,0.04)]",
};

export function PipelineFlow({ status }: PipelineFlowProps) {
  return (
    <div className="card-glass">
      <p className="text-label mb-4">Agent Pipeline</p>
      <div className="flex flex-wrap items-center gap-2">
        {AGENTS.map((agent, i) => {
          const nodeStatus = getNodeStatus(agent, status);
          const Icon = statusIcons[nodeStatus];
          const isLast = i === AGENTS.length - 1;

          return (
            <div key={agent} className="flex items-center gap-2">
              <div
                className={`flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 transition-all duration-200 ${statusBg[nodeStatus]}`}
                title={agentLabels[agent]}
              >
                <Icon size={12} className={statusColors[nodeStatus]} />
                <span
                  className={`font-mono text-xs ${statusColors[nodeStatus]}`}
                >
                  {agentLabels[agent]}
                </span>
              </div>
              {!isLast && (
                <span className="text-[rgba(255,255,255,0.12)]">→</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
