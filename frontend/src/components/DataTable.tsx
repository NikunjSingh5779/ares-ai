"use client";

import type { ReactNode } from "react";

export interface Column<T> {
  key: string;
  label: string;
  render?: (item: T) => ReactNode;
  className?: string;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  emptyMessage?: string;
}

export function DataTable<T extends object>({
  columns,
  data,
  emptyMessage = "No data",
}: DataTableProps<T>) {
  if (data.length === 0) {
    return (
      <div className="flex items-center justify-center rounded-lg border border-dashed border-[oklch(0.25_0_0)] p-8">
        <p className="font-mono text-sm text-[oklch(0.38_0_0)]">
          {emptyMessage}
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-[oklch(0.25_0_0)]">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-[oklch(0.25_0_0)] bg-[oklch(0.13_0_0)]">
            {columns.map((col) => (
              <th
                key={col.key}
                className={`px-4 py-2.5 font-mono text-xs font-medium text-[oklch(0.6_0_0)] uppercase tracking-wider ${col.className || ""}`}
              >
                {col.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.map((item, i) => (
            <tr
              key={i}
              className="border-b border-[oklch(0.25_0_0)] transition-colors last:border-0 hover:bg-[oklch(0.22_0.01_145)]"
            >
              {columns.map((col) => (
                <td
                  key={col.key}
                  className={`px-4 py-2.5 font-mono text-sm text-[oklch(0.88_0_0)] ${col.className || ""}`}
                >
                  {col.render
                    ? col.render(item)
                    : String((item as Record<string, unknown>)[col.key] ?? "")}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
