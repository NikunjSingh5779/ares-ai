"use client";

type BadgeVariant = "ok" | "failed" | "skipped" | "running" | "default";

interface StatusBadgeProps {
  status: BadgeVariant | string;
  label?: string;
}

const variantStyles: Record<string, string> = {
  ok: "bg-[oklch(0.25_0.08_145)] text-[oklch(0.62_0.19_145)]",
  completed: "bg-[oklch(0.25_0.08_145)] text-[oklch(0.62_0.19_145)]",
  failed: "bg-[oklch(0.25_0.08_30)] text-[oklch(0.55_0.22_30)]",
  skipped: "bg-[oklch(0.25_0_0)] text-[oklch(0.5_0_0)]",
  running: "bg-[oklch(0.25_0.08_250)] text-[oklch(0.6_0.15_250)]",
  approved: "bg-[oklch(0.25_0.08_145)] text-[oklch(0.62_0.19_145)]",
  rejected: "bg-[oklch(0.25_0.08_30)] text-[oklch(0.55_0.22_30)]",
  default: "bg-[oklch(0.2_0_0)] text-[oklch(0.5_0_0)]",
};

export function StatusBadge({ status, label }: StatusBadgeProps) {
  const style = variantStyles[status.toLowerCase()] || variantStyles.default;
  const display = label || status;

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 font-mono text-xs font-medium ${style}`}
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
