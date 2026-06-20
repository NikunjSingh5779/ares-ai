"use client";

import { CheckCircle2, XCircle, SkipForward, Play, type LucideIcon } from "lucide-react";
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
  status: PipelineStatus | null,
): NodeStatus {
  if (!status) return "pending";
  if (status.failed_nodes.includes(agent)) return "failed";
  if (status.completed_nodes.includes(agent)) return "completed";
  if (status.skipped_nodes.includes(agent)) return "skipped";
  if (status.current_node === agent) return "completed"; // In-progress treated as pending visually
  return "pending";
}

const statusIcons: Record<NodeStatus, LucideIcon> = {
  completed: CheckCircle2,
  failed: XCircle,
  skipped: SkipForward,
  pending: Play,
};

const statusColors: Record<NodeStatus, string> = {
  completed: "text-[oklch(0.62_0.19_145)]",
  failed: "text-[oklch(0.55_0.22_30)]",
  skipped: "text-[oklch(0.38_0_0)]",
  pending: "text-[oklch(0.3_0_0)]",
};

const statusBg: Record<NodeStatus, string> = {
  completed: "bg-[oklch(0.25_0.08_145)]",
  failed: "bg-[oklch(0.25_0.08_30)]",
  skipped: "bg-[oklch(0.15_0_0)]",
  pending: "bg-[oklch(0.15_0_0)]",
};

export function PipelineFlow({ status }: PipelineFlowProps) {
  return (
    <div className="rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.13_0_0)] p-4">
      <p className="mb-4 font-mono text-xs font-medium text-[oklch(0.6_0_0)] uppercase tracking-wider">
        Agent Pipeline
      </p>
      <div className="flex flex-wrap items-center gap-2">
        {AGENTS.map((agent, i) => {
          const nodeStatus = getNodeStatus(agent, status);
          const Icon = statusIcons[nodeStatus];
          const isLast = i === AGENTS.length - 1;

          return (
            <div key={agent} className="flex items-center gap-2">
              <div
                className={`flex items-center gap-1.5 rounded-md px-2.5 py-1.5 ${statusBg[nodeStatus]}`}
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
                <span className="text-[oklch(0.25_0_0)]">→</span>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
