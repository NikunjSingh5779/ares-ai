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
  MarketAnalystOutput,
  MetricsResponse,
  OpenPosition,
  PaperRecord,
  PortfolioSummary,
  QuantOutput,
  RiskOutput,
  SignalResponse,
  VisionOutput,
  SignalHistoryEntry,
  AnalyzeResponse,
  ChatResponse,
  ChatTurn,
  JournalHistoryEntry,
  BacktestResult,
  BacktestMetrics,
  CandlesResponse,
  SettingsResponse,
  DashboardPreferences,
  Strategy,
  StrategyInput,
} from "@/types/api";
import { clearApiKey, getApiKey } from "./auth";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

const BASE = API_BASE_URL;

/** Default request budget. Long-running calls can override this. */
const DEFAULT_TIMEOUT_MS = 30_000;
const VERIFY_TIMEOUT_MS = 10_000;

export class ApiError extends Error {
  status: number;
  detail?: unknown;

  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

export class ApiTimeoutError extends Error {
  timeoutMs: number;

  constructor(timeoutMs: number) {
    super(`Request timed out after ${Math.round(timeoutMs / 1000)}s`);
    this.name = "ApiTimeoutError";
    this.timeoutMs = timeoutMs;
  }
}

interface RequestOptions extends RequestInit {
  /** Per-request timeout in ms. Defaults to 30s. */
  timeoutMs?: number;
}

function formatDetail(detail: unknown): string | null {
  if (typeof detail === "string" && detail.trim()) return detail.trim();
  if (Array.isArray(detail)) {
    const messages = detail
      .map((item) => {
        if (typeof item === "string") return item;
        if (item && typeof item === "object" && "msg" in item) {
          return String((item as { msg: unknown }).msg);
        }
        return "";
      })
      .filter(Boolean);
    if (messages.length > 0) return messages.join("; ");
  }
  if (detail && typeof detail === "object" && "message" in detail) {
    return String((detail as { message: unknown }).message);
  }
  return null;
}

async function readApiError(res: Response, path: string): Promise<ApiError> {
  let raw = "";
  try {
    raw = await res.text();
  } catch {
    // The status remains useful even if the body cannot be read.
  }

  let detail: unknown = raw || null;
  if (raw) {
    try {
      const parsed: unknown = JSON.parse(raw);
      detail =
        parsed && typeof parsed === "object" && "detail" in parsed
          ? (parsed as { detail: unknown }).detail
          : parsed;
    } catch {
      detail = raw;
    }
  }

  const message = formatDetail(detail) ?? `API ${res.status} on ${path}`;
  return new ApiError(res.status, message, detail);
}

async function request<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { timeoutMs = DEFAULT_TIMEOUT_MS, signal: callerSignal, ...init } = options;
  const headers = new Headers(init.headers);
  headers.set("Content-Type", "application/json");
  const key = getApiKey();
  if (key) headers.set("X-API-Key", key);

  const controller = new AbortController();
  let timedOut = false;
  const abortFromCaller = () => controller.abort();

  if (callerSignal) {
    if (callerSignal.aborted) controller.abort();
    else callerSignal.addEventListener("abort", abortFromCaller, { once: true });
  }

  const timeout = setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);

  try {
    const res = await fetch(`${BASE}${path}`, {
      ...init,
      headers,
      cache: "no-store",
      signal: controller.signal,
    });

    if (res.status === 401) {
      clearApiKey();
      if (typeof window !== "undefined" && window.location.pathname !== "/login") {
        window.location.replace("/login");
      }
    }

    if (!res.ok) {
      throw await readApiError(res, path);
    }
    if (res.status === 204) {
      return undefined as T;
    }
    return res.json() as Promise<T>;
  } catch (error) {
    if (timedOut) throw new ApiTimeoutError(timeoutMs);
    throw error;
  } finally {
    clearTimeout(timeout);
    callerSignal?.removeEventListener("abort", abortFromCaller);
  }
}

/** Validate an API key before storing it in the session. */
export async function verifyApiKey(key: string): Promise<boolean> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), VERIFY_TIMEOUT_MS);
  try {
    const res = await fetch(`${BASE}/auth/verify`, {
      headers: { "X-API-Key": key },
      cache: "no-store",
      signal: controller.signal,
    });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timeout);
  }
}

// ─── Analysis ───────────────────────────────────────────────────

export async function analyze(
  symbol: string,
  requestText = "Analyze",
): Promise<AnalyzeResponse> {
  return request<AnalyzeResponse>("/api/v1/analyze", {
    method: "POST",
    body: JSON.stringify({ symbol, request: requestText }),
    timeoutMs: 20_000,
  });
}

/** Send a bounded conversation to the read-only assistant. */
export async function sendChatMessage(
  messages: ChatTurn[],
): Promise<ChatResponse> {
  return request<ChatResponse>("/api/v1/chat", {
    method: "POST",
    body: JSON.stringify({ messages }),
    timeoutMs: 60_000,
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

export async function getSignalHistory(): Promise<SignalHistoryEntry[]> {
  return request<SignalHistoryEntry[]>("/api/v1/signals/history");
}

// ─── Market data ────────────────────────────────────────────────

export async function getCandles(
  symbol: string,
  interval = "1d",
  limit = 120,
  signal?: AbortSignal,
): Promise<CandlesResponse> {
  const params = new URLSearchParams({
    symbol,
    interval,
    limit: String(limit),
  });
  return request<CandlesResponse>(`/api/v1/market/candles?${params.toString()}`, {
    signal,
    timeoutMs: 20_000,
  });
}

// ─── Settings ───────────────────────────────────────────────────

export async function getSettings(signal?: AbortSignal): Promise<SettingsResponse> {
  return request<SettingsResponse>("/api/v1/settings", { signal });
}

export async function updateSettingsPreferences(
  preferences: DashboardPreferences,
): Promise<SettingsResponse> {
  return request<SettingsResponse>("/api/v1/settings/preferences", {
    method: "PUT",
    body: JSON.stringify(preferences),
  });
}

// Strategy drafts

export async function listStrategies(signal?: AbortSignal): Promise<Strategy[]> {
  return request<Strategy[]>("/api/v1/strategies", {
    signal,
    timeoutMs: 10_000,
  });
}

export async function createStrategy(payload: StrategyInput): Promise<Strategy> {
  return request<Strategy>("/api/v1/strategies", {
    method: "POST",
    body: JSON.stringify(payload),
    timeoutMs: 10_000,
  });
}

export async function updateStrategy(
  strategyId: string,
  payload: Partial<StrategyInput>,
): Promise<Strategy> {
  return request<Strategy>(`/api/v1/strategies/${encodeURIComponent(strategyId)}`, {
    method: "PUT",
    body: JSON.stringify(payload),
    timeoutMs: 10_000,
  });
}

export async function runBacktest(body: {
  symbol: string;
  interval?: string;
  initial_capital?: number;
  strategy?: string;
  days_back?: number;
}): Promise<BacktestResult> {
  return request<BacktestResult>("/api/v1/backtest/run", {
    method: "POST",
    body: JSON.stringify(body),
    timeoutMs: 120_000,
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
  client_order_id: string;
  symbol: string;
  side: "long" | "short";
  approval: {
    market_analyst_output: MarketAnalystOutput;
    quant_output: QuantOutput;
    risk_output: RiskOutput;
    vision_output?: VisionOutput | null;
  };
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

export async function getJournalHistory(): Promise<JournalHistoryEntry[]> {
  return request<JournalHistoryEntry[]>("/api/v1/journal/history");
}

export async function getMemory(): Promise<{
  relevant_memories: Array<Record<string, unknown>>;
  consolidated: boolean;
  rationale: string;
}> {
  return request("/api/v1/memory");
}

// ─── Agents ─────────────────────────────────────────────────────

export async function getAgentStatus(signal?: AbortSignal): Promise<AgentStatusResponse> {
  return request<AgentStatusResponse>("/api/v1/agents/status", {
    signal,
    timeoutMs: 10_000,
  });
}

// ─── Monitoring ─────────────────────────────────────────────────

export async function getMetrics(): Promise<MetricsResponse> {
  return request<MetricsResponse>("/api/v1/metrics");
}

export async function getRisk(): Promise<RiskOutput> {
  return request<RiskOutput>("/api/v1/risk");
}

// ─── Live Trading ──────────────────────────────────────────────

export async function getLiveStatus(signal?: AbortSignal): Promise<LiveStatusResponse> {
  return request<LiveStatusResponse>("/api/v1/live/status", {
    signal,
    timeoutMs: 10_000,
  });
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

export async function getLiveAudit(
  limit = 50,
  signal?: AbortSignal,
): Promise<AuditEntry[]> {
  return request<AuditEntry[]>(`/api/v1/live/audit?limit=${limit}`, {
    signal,
    timeoutMs: 10_000,
  });
}

export async function getPaperRecord(): Promise<PaperRecord> {
  return request<PaperRecord>("/api/v1/live/paper_record");
}
