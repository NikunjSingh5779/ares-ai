/* ─── ARES AI API Client ─────────────────────────────────────────
 * Typed fetch wrappers for every backend endpoint.
 * All calls go to the FastAPI backend at localhost:8000.
 * ──────────────────────────────────────────────────────────────── */

import type {
  AgentState,
  AgentStatusResponse,
  AuditEntry,
  ClosedTrade,
  LiveOrder,
  LivePosition,
  LiveStatusResponse,
  MetricsResponse,
  OpenPosition,
  PaperRecord,
  PortfolioSummary,
  RiskOutput,
  SignalResponse,
} from "@/types/api";

const BASE = "http://localhost:8000";

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status} on ${path}: ${body}`);
  }
  return res.json() as Promise<T>;
}

// ─── Analysis ───────────────────────────────────────────────────

export async function analyze(
  symbol: string,
  requestText = "Analyze",
): Promise<AgentState> {
  return request<AgentState>("/api/v1/analyze", {
    method: "POST",
    body: JSON.stringify({ symbol, request: requestText }),
  });
}

export async function getSignal(
  symbol: string,
  requestText = "Analyze",
): Promise<SignalResponse> {
  return request<SignalResponse>("/api/v1/signal", {
    method: "POST",
    body: JSON.stringify({ symbol, request: requestText }),
  });
}

// ─── Trading ────────────────────────────────────────────────────

export async function getPortfolio(): Promise<PortfolioSummary> {
  return request<PortfolioSummary>("/api/v1/portfolio");
}

export async function getPositions(): Promise<OpenPosition[]> {
  return request<OpenPosition[]>("/api/v1/positions");
}

export async function getOrders(): Promise<ClosedTrade[]> {
  return request<ClosedTrade[]>("/api/v1/orders");
}

export async function executeTrade(body: {
  symbol: string;
  side: string;
  quantity: number;
  entry_price: number;
  stop_loss?: number;
  take_profit?: number;
  strategy_name?: string;
}): Promise<Record<string, unknown>> {
  return request<Record<string, unknown>>("/api/v1/execute", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

// ─── Journal & Memory ───────────────────────────────────────────

export async function getJournal(): Promise<{
  entry_id: string | null;
  mistakes: string[];
  lessons: string[];
  rationale: string;
}> {
  return request("/api/v1/journal");
}

export async function getMemory(): Promise<{
  relevant_memories: Array<Record<string, unknown>>;
  consolidated: boolean;
  rationale: string;
}> {
  return request("/api/v1/memory");
}

// ─── Agents ─────────────────────────────────────────────────────

export async function getAgentStatus(): Promise<AgentStatusResponse> {
  return request<AgentStatusResponse>("/api/v1/agents/status");
}

// ─── Monitoring ─────────────────────────────────────────────────

export async function getMetrics(): Promise<MetricsResponse> {
  return request<MetricsResponse>("/api/v1/metrics");
}

export async function getRisk(): Promise<RiskOutput> {
  return request<RiskOutput>("/api/v1/risk");
}

// ─── Live Trading ──────────────────────────────────────────────

export async function getLiveStatus(): Promise<LiveStatusResponse> {
  return request<LiveStatusResponse>("/api/v1/live/status");
}

export async function setLiveMode(mode: string): Promise<{ mode: string }> {
  return request<{ mode: string }>("/api/v1/live/mode", {
    method: "POST",
    body: JSON.stringify({ mode }),
  });
}

export async function startLiveEngine(): Promise<{
  status: string;
  connected: boolean;
}> {
  return request("/api/v1/live/start", { method: "POST" });
}

export async function stopLiveEngine(): Promise<{ status: string }> {
  return request("/api/v1/live/stop", { method: "POST" });
}

export async function activateKillSwitch(
  reason = "manual",
): Promise<{ status: string; triggered_by: string }> {
  return request("/api/v1/live/kill", {
    method: "POST",
    body: JSON.stringify({ reason }),
  });
}

export async function armKillSwitch(): Promise<{ status: string }> {
  return request("/api/v1/live/arm", { method: "POST" });
}

export async function getLivePositions(): Promise<LivePosition[]> {
  return request<LivePosition[]>("/api/v1/live/positions");
}

export async function getLiveOrders(): Promise<LiveOrder[]> {
  return request<LiveOrder[]>("/api/v1/live/orders");
}

export async function getLiveAudit(limit = 50): Promise<AuditEntry[]> {
  return request<AuditEntry[]>(`/api/v1/live/audit?limit=${limit}`);
}

export async function getPaperRecord(): Promise<PaperRecord> {
  return request<PaperRecord>("/api/v1/live/paper_record");
}
