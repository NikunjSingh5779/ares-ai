/* ─── ARES AI API Types ──────────────────────────────────────────
 * Mirrors the Pydantic models from agents/state.py and
 * paper_trading/engine.py for type-safe frontend access.
 * ────────────────────────────────────────────────────────────── */

// ─── Agent Outputs ──────────────────────────────────────────────

export interface MarketAnalystOutput {
  confidence: number;
  direction: "long" | "short" | "flat";
  indicators: Record<string, number>;
  rationale: string;
}

export interface QuantOutput {
  confidence: number;
  direction: "long" | "short" | "flat";
  expected_return?: number | null;
  strategy_name: string;
  params: Record<string, unknown>;
  rationale: string;
}

export interface NewsOutput {
  sentiment: number;
  key_events: string[];
  impact_scores: Record<string, number>;
  sources: string[];
  rationale: string;
}

export interface RiskOutput {
  approved: boolean;
  max_position_size?: number | null;
  stop_loss?: number | null;
  risk_score: number;
  reasons: string[];
  rationale: string;
}

export interface ConsensusOutput {
  approved: boolean;
  composite_confidence: number;
  agreement_metrics: Record<string, unknown>;
  rationale: string;
}

export interface ExecutionOutput {
  executed: boolean;
  order_id?: string | null;
  fill_price?: number | null;
  filled_quantity?: number | null;
  rationale: string;
}

export interface JournalOutput {
  entry_id?: string | null;
  mistakes: string[];
  lessons: string[];
  rationale: string;
}

export interface ReflectionOutput {
  evaluation: string;
  confidence_accuracy: number;
  improvement_suggestions: string[];
  knowledge_updates: string[];
}

export interface MemoryOutput {
  relevant_memories: MemoryRecord[];
  consolidated: boolean;
  rationale: string;
}

export interface MemoryRecord {
  type: "trade" | "agent_output" | "user_preference";
  content: string;
  importance: number;
  metadata?: Record<string, unknown>;
}

export interface VisionOutput {
  chart_pattern?: string | null;
  confidence: number;
  support_levels: number[];
  resistance_levels: number[];
  available: boolean;
  rationale: string;
}

// ─── Pipeline Status ────────────────────────────────────────────

export interface PipelineStatus {
  current_node: string;
  completed_nodes: string[];
  failed_nodes: string[];
  skipped_nodes: string[];
  start_time?: string | null;
  end_time?: string | null;
}

// ─── Agent State (full pipeline result) ─────────────────────────

export interface AgentState {
  request_id: string;
  session_id: string;
  symbol: string;
  request: string;
  request_type: string;
  pipeline_status: PipelineStatus;
  errors: Array<{ agent: string; error: string; error_type: string }>;
  model_chain_used: Record<string, string[]>;
  degraded: boolean;
  total_latency_ms: number;

  market_analyst?: MarketAnalystOutput | null;
  quant?: QuantOutput | null;
  news?: NewsOutput | null;
  vision?: VisionOutput | null;
  consensus?: ConsensusOutput | null;
  risk?: RiskOutput | null;
  execution?: ExecutionOutput | null;
  journal?: JournalOutput | null;
  reflection?: ReflectionOutput | null;
  memory?: MemoryOutput | null;
}

// ─── Portfolio & Trading ────────────────────────────────────────

export interface PortfolioSummary {
  initial_capital: number;
  cash: number;
  total_pnl: number;
  total_return_pct: number;
  win_rate: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  open_positions: number;
  max_drawdown_pct: number;
}

export interface OpenPosition {
  id: string;
  symbol: string;
  side: "long" | "short";
  quantity: number;
  entry_price: number;
  entry_at: string;
  stop_loss?: number | null;
  take_profit?: number | null;
  strategy_name: string;
}

export interface ClosedTrade {
  symbol: string;
  side: "long" | "short";
  quantity: number;
  entry_price: number;
  exit_price: number;
  entry_at: string;
  exit_at: string;
  pnl: number;
  pnl_pct: number;
  exit_reason: string;
  strategy_name: string;
}

// ─── Signal Response ────────────────────────────────────────────

export interface SignalResponse {
  status: string;
  approved: boolean;
  executed: boolean;
  symbol: string;
  confidence: number;
  direction: string;
  rationale: string;
  pipeline_status: PipelineStatus;
  errors: Array<{ agent: string; error: string; error_type: string }>;
}

export interface SignalHistoryEntry {
  id: string;
  symbol: string;
  direction: string;
  confidence: number;
  composite_confidence: number;
  market_analyst_confidence: number;
  quant_confidence: number;
  news_sentiment: number;
  risk_score: number;
  risk_approved: boolean;
  is_consensus: boolean;
  rationale: string;
  is_executed: boolean;
  created_at: string;
  agent_outputs?: Record<string, unknown>;
}

export interface AnalyzeResponse {
  status: string;
  message: string;
  session_id: string;
}

// ─── Agent Status ───────────────────────────────────────────────

export interface AgentStatusResponse extends AgentState {
  has_run: boolean;
}

// ─── Metrics & Risk ─────────────────────────────────────────────

export interface MetricsResponse {
  total_runs: number;
  total_agents_executed: number;
  total_errors: number;
  total_failures: number;
  degraded: boolean;
  total_latency_ms: number;
}

// ─── Journal & History ──────────────────────────────────────────

export interface JournalHistoryEntry {
  id: string;
  entry_type: string;
  title: string;
  content: string;
  sentiment: string;
  mistakes_detected: string[];
  lessons_learned: string[];
  created_at: string;
}

// ─── Live Trading ──────────────────────────────────────────────

export interface LiveStatusResponse {
  running: boolean;
  connected: boolean;
  mode: "human_approval" | "semi" | "auto";
  kill_switch: {
    active: boolean;
    triggered_by: string | null;
    triggered_at: string | null;
    max_drawdown_pct: number;
  };
  exchange: string;
  paper_record: PaperRecord;
}

export interface PaperRecord {
  trades: number;
  days: number;
  promotion: {
    trades: { current: number; required: number };
    days: { current: number; required: number };
    passed: boolean;
  };
}

export interface LivePosition {
  symbol: string;
  side: "long" | "short";
  quantity: number;
  entry_price: number;
  unrealized_pnl: number;
}

export interface LiveOrder {
  id: string;
  symbol: string;
  side: "buy" | "sell";
  type: string;
  quantity: number;
  price: number | null;
  filled: number;
  remaining: number;
  status: string;
}

export interface AuditEntry {
  order_intent: Record<string, unknown>;
  agent_chain: Record<string, unknown>[];
  risk_checks: Record<string, unknown>[];
  order_result: Record<string, unknown> | null;
  timestamp: string;
}
