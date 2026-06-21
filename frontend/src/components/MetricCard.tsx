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
    <div className="card-glass group">
      <p className="text-label mb-2">{label}</p>
      <p className="font-sans text-2xl font-bold tracking-tight text-white">
        {value}
        {unit && (
          <span className="ml-1 text-sm font-normal text-[#a1a1aa]">
            {unit}
          </span>
        )}
      </p>
      {change !== null && change !== undefined && (
        <div className="mt-2 flex items-center gap-1.5">
          {isPositive && (
            <span className="flex items-center gap-0.5 rounded-full bg-[rgba(34,197,94,0.12)] px-2 py-0.5">
              <ArrowUpRight size={12} className="text-[#22c55e]" />
              <span className="font-mono text-xs font-medium text-[#22c55e]">
                +{change.toFixed(2)}%
              </span>
            </span>
          )}
          {isNegative && (
            <span className="flex items-center gap-0.5 rounded-full bg-[rgba(239,68,68,0.12)] px-2 py-0.5">
              <ArrowDownRight size={12} className="text-[#ef4444]" />
              <span className="font-mono text-xs font-medium text-[#ef4444]">
                {change.toFixed(2)}%
              </span>
            </span>
          )}
          {!isPositive && !isNegative && (
            <span className="flex items-center gap-0.5 rounded-full bg-[rgba(255,255,255,0.05)] px-2 py-0.5">
              <Minus size={12} className="text-[#52525b]" />
              <span className="font-mono text-xs text-[#52525b]">
                {change.toFixed(2)}%
              </span>
            </span>
          )}
        </div>
      )}
    </div>
  );
}
