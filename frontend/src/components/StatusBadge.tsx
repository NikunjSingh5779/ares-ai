"use client";

type BadgeVariant = "ok" | "failed" | "skipped" | "running" | "default";

interface StatusBadgeProps {
  status: BadgeVariant | string;
  label?: string;
}

const variantStyles: Record<string, string> = {
  ok: "bg-[rgba(34,197,94,0.12)] text-[#22c55e] border-[rgba(34,197,94,0.2)]",
  completed:
    "bg-[rgba(34,197,94,0.12)] text-[#22c55e] border-[rgba(34,197,94,0.2)]",
  failed:
    "bg-[rgba(239,68,68,0.12)] text-[#ef4444] border-[rgba(239,68,68,0.2)]",
  skipped:
    "bg-[rgba(255,255,255,0.04)] text-[#52525b] border-[rgba(255,255,255,0.08)]",
  running:
    "bg-[rgba(99,102,241,0.12)] text-[#6366f1] border-[rgba(99,102,241,0.2)]",
  approved:
    "bg-[rgba(34,197,94,0.12)] text-[#22c55e] border-[rgba(34,197,94,0.2)]",
  rejected:
    "bg-[rgba(239,68,68,0.12)] text-[#ef4444] border-[rgba(239,68,68,0.2)]",
  pending:
    "bg-[rgba(245,158,11,0.12)] text-[#f59e0b] border-[rgba(245,158,11,0.2)]",
  default:
    "bg-[rgba(255,255,255,0.04)] text-[#52525b] border-[rgba(255,255,255,0.08)]",
};

export function StatusBadge({ status, label }: StatusBadgeProps) {
  const style =
    variantStyles[status.toLowerCase()] || variantStyles.default;
  const display = label || status;

  return (
    <span
      className={`inline-flex items-center rounded-full border px-2.5 py-0.5 font-mono text-xs font-medium transition-colors ${style}`}
    >
      <span
        className={`mr-1.5 inline-block h-1.5 w-1.5 rounded-full ${
          status === "running" ? "animate-pulse bg-current" : "bg-current"
        }`}
      />
      {display}
    </span>
  );
}
