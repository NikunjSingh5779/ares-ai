"use client";

import { useEffect, useState } from "react";
import { RefreshCw, Shield, AlertTriangle, CheckCircle, XCircle } from "lucide-react";
import { MetricCard } from "@/components/MetricCard";
import { getRisk, getPortfolio } from "@/lib/api";
import type { RiskOutput, PortfolioSummary } from "@/types/api";

export default function RiskPage() {
  const [risk, setRisk] = useState<RiskOutput | null>(null);
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [r, p] = await Promise.all([
        getRisk().catch(() => null),
        getPortfolio().catch(() => null),
      ]);
      setRisk(r);
      setPortfolio(p);
    } catch {
      setError("Could not fetch risk data");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    loadData();
  }, []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-heading text-xl text-white">Risk Management</h1>
          <p className="text-label mt-1">Portfolio Risk & Exposure Analysis</p>
        </div>
        <button
          onClick={loadData}
          disabled={loading}
          className="btn-primary !py-2 !px-3 !text-xs !font-mono disabled:opacity-50"
        >
          <Shield size={12} />
          {loading ? "Loading..." : "Refresh"}
        </button>
      </div>

      {error && (
        <div className="rounded-xl border border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.08)] px-4 py-3">
          <p className="font-mono text-xs text-[#ef4444]">{error}</p>
        </div>
      )}

      {/* Risk Approval Status */}
      {risk && (
        <div className={`rounded-xl border p-5 ${
          risk.approved
            ? "border-[rgba(34,197,94,0.2)] bg-[rgba(34,197,94,0.06)]"
            : "border-[rgba(239,68,68,0.2)] bg-[rgba(239,68,68,0.06)]"
        }`}>
          <div className="flex items-center gap-3">
            {risk.approved ? (
              <CheckCircle size={24} className="text-[#22c55e]" />
            ) : (
              <XCircle size={24} className="text-[#ef4444]" />
            )}
            <div>
              <p className={`font-sans text-lg font-bold ${
                risk.approved ? "text-[#22c55e]" : "text-[#ef4444]"
              }`}>
                {risk.approved ? "Approved" : "Rejected"}
              </p>
              <p className="font-mono text-xs text-[#a1a1aa]">
                Risk Score: {risk.risk_score.toFixed(2)}
              </p>
            </div>
          </div>
        </div>
      )}

      {loading && !risk && (
        <div className="flex items-center justify-center py-12">
          <RefreshCw size={16} className="animate-spin text-[#6366f1]" />
        </div>
      )}

      {/* Risk Metrics */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {risk && (
          <>
            <MetricCard
              label="Risk Score"
              value={risk.risk_score.toFixed(2)}
            />
            <MetricCard
              label="Max Position Size"
              value={risk.max_position_size != null ? `$${risk.max_position_size.toLocaleString()}` : "N/A"}
            />
            <MetricCard
              label="Stop Loss"
              value={risk.stop_loss != null ? `${risk.stop_loss.toFixed(1)}%` : "N/A"}
            />
          </>
        )}
        {portfolio && (
          <>
            <MetricCard
              label="Total P&L"
              value={`$${portfolio.total_pnl.toLocaleString()}`}
              change={portfolio.total_pnl > 0 ? portfolio.total_return_pct : -portfolio.total_return_pct}
            />
            <MetricCard
              label="Max Drawdown"
              value={`${portfolio.max_drawdown_pct.toFixed(1)}%`}
              change={portfolio.max_drawdown_pct > 0 ? -(portfolio.max_drawdown_pct) : null}
            />
            <MetricCard
              label="Win Rate"
              value={`${portfolio.win_rate.toFixed(1)}%`}
              change={portfolio.win_rate}
            />
          </>
        )}
      </div>

      {/* Rejection Reasons */}
      {risk && !risk.approved && risk.reasons.length > 0 && (
        <div className="card-glass">
          <div className="flex items-center gap-2 mb-4">
            <AlertTriangle size={14} className="text-[#f59e0b]" />
            <p className="text-label">Rejection Reasons</p>
          </div>
          <ul className="space-y-2">
            {risk.reasons.map((reason, i) => (
              <li
                key={i}
                className="flex items-start gap-2 rounded-lg bg-[rgba(239,68,68,0.06)] border border-[rgba(239,68,68,0.12)] px-3 py-2"
              >
                <span className="mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[#ef4444]" />
                <span className="font-mono text-xs text-[#e4e4e7]">{reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Rationale */}
      {risk?.rationale && (
        <div className="card-glass">
          <p className="text-label mb-3">Risk Assessment Rationale</p>
          <p className="font-mono text-xs text-[#a1a1aa] leading-relaxed">
            {risk.rationale}
          </p>
        </div>
      )}
    </div>
  );
}
