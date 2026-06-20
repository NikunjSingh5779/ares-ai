"use client";

import { ArrowUpRight, ArrowDownRight, Minus } from "lucide-react";

interface MetricCardProps {
  label: string;
  value: string;
  change?: number | null;
  unit?: string;
}

export function MetricCard({ label, value, change, unit }: MetricCardProps) {
  const isPositive = change !== null && change !== undefined && change > 0;
  const isNegative = change !== null && change !== undefined && change < 0;

  return (
    <div className="rounded-lg border border-[oklch(0.25_0_0)] bg-[oklch(0.18_0.01_145)] p-4">
      <p className="mb-1 font-mono text-xs text-[oklch(0.6_0_0)]">{label}</p>
      <p className="font-mono text-2xl font-semibold text-[oklch(0.92_0_0)] tracking-tight">
        {value}
        {unit && (
          <span className="ml-1 text-sm text-[oklch(0.6_0_0)]">{unit}</span>
        )}
      </p>
      {change !== null && change !== undefined && (
        <div className="mt-1 flex items-center gap-1">
          {isPositive && (
            <ArrowUpRight size={14} className="text-[oklch(0.62_0.19_145)]" />
          )}
          {isNegative && (
            <ArrowDownRight size={14} className="text-[oklch(0.55_0.22_30)]" />
          )}
          {!isPositive && !isNegative && (
            <Minus size={14} className="text-[oklch(0.6_0_0)]" />
          )}
          <span
            className={`font-mono text-xs ${
              isPositive
                ? "text-[oklch(0.62_0.19_145)]"
                : isNegative
                  ? "text-[oklch(0.55_0.22_30)]"
                  : "text-[oklch(0.6_0_0)]"
            }`}
          >
            {change > 0 ? "+" : ""}
            {change.toFixed(2)}%
          </span>
        </div>
      )}
    </div>
  );
}
