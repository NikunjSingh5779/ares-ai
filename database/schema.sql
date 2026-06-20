-- =============================================================================
-- ARES AI — Database Schema (PostgreSQL 16+)
-- =============================================================================
-- All 17 tables for the ARES AI trading platform.
-- Run this against a fresh PostgreSQL 16+ database to initialize.
-- =============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ===========================================================================
-- USERS & ACCOUNTS
-- ===========================================================================

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'user'
        CHECK (role IN ('user', 'admin', 'super_admin')),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE accounts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exchange VARCHAR(50) NOT NULL,
    account_name VARCHAR(100) NOT NULL,
    api_key_encrypted TEXT,
    api_secret_encrypted TEXT,
    is_active BOOLEAN NOT NULL DEFAULT false,
    trading_mode VARCHAR(20) NOT NULL DEFAULT 'human_approval'
        CHECK (trading_mode IN ('human_approval', 'semi_autonomous', 'full_autonomous')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, exchange, account_name)
);

-- ===========================================================================
-- PORTFOLIO & POSITIONS
-- ===========================================================================

CREATE TABLE portfolio (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    total_value NUMERIC(20, 8) NOT NULL DEFAULT 0,
    cash_balance NUMERIC(20, 8) NOT NULL DEFAULT 0,
    invested_amount NUMERIC(20, 8) NOT NULL DEFAULT 0,
    unrealized_pnl NUMERIC(20, 8) NOT NULL DEFAULT 0,
    realized_pnl NUMERIC(20, 8) NOT NULL DEFAULT 0,
    roi_pct NUMERIC(10, 4) NOT NULL DEFAULT 0,
    max_drawdown_pct NUMERIC(10, 4) NOT NULL DEFAULT 0,
    currency VARCHAR(10) NOT NULL DEFAULT 'USD',
    last_rebalanced_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE positions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    portfolio_id UUID NOT NULL REFERENCES portfolio(id) ON DELETE CASCADE,
    symbol VARCHAR(20) NOT NULL,
    asset_type VARCHAR(20) NOT NULL
        CHECK (asset_type IN ('crypto', 'stock', 'forex', 'commodity', 'etf', 'option')),
    quantity NUMERIC(20, 8) NOT NULL DEFAULT 0,
    entry_price NUMERIC(20, 8) NOT NULL DEFAULT 0,
    current_price NUMERIC(20, 8) NOT NULL DEFAULT 0,
    market_value NUMERIC(20, 8) NOT NULL DEFAULT 0,
    unrealized_pnl NUMERIC(20, 8) NOT NULL DEFAULT 0,
    unrealized_pnl_pct NUMERIC(10, 4) NOT NULL DEFAULT 0,
    stop_loss NUMERIC(20, 8),
    take_profit NUMERIC(20, 8),
    strategy_name VARCHAR(100),
    opened_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    closed_at TIMESTAMPTZ,
    is_open BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_positions_portfolio_id ON positions(portfolio_id);
CREATE INDEX idx_positions_symbol ON positions(symbol);
CREATE INDEX idx_positions_open ON positions(is_open) WHERE is_open = true;

-- ===========================================================================
-- ORDERS
-- ===========================================================================

CREATE TABLE orders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    position_id UUID REFERENCES positions(id),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    order_type VARCHAR(20) NOT NULL
        CHECK (order_type IN ('market', 'limit', 'stop', 'stop_limit', 'trailing_stop')),
    quantity NUMERIC(20, 8) NOT NULL,
    price NUMERIC(20, 8),
    stop_price NUMERIC(20, 8),
    filled_quantity NUMERIC(20, 8) NOT NULL DEFAULT 0,
    avg_fill_price NUMERIC(20, 8),
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'open', 'filled', 'partially_filled', 'cancelled', 'rejected', 'expired')),
    exchange_order_id VARCHAR(100),
    failure_reason TEXT,
    agent_rationale JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_orders_account_id ON orders(account_id);
CREATE INDEX idx_orders_status ON orders(status);
CREATE INDEX idx_orders_created_at ON orders(created_at DESC);

-- ===========================================================================
-- SIGNALS
-- ===========================================================================

CREATE TABLE signals (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    symbol VARCHAR(20) NOT NULL,
    direction VARCHAR(10) NOT NULL CHECK (direction IN ('long', 'short', 'flat')),
    confidence NUMERIC(5, 2) NOT NULL CHECK (confidence >= 0 AND confidence <= 100),
    composite_confidence NUMERIC(5, 2),
    market_analyst_confidence NUMERIC(5, 2),
    quant_confidence NUMERIC(5, 2),
    news_sentiment NUMERIC(5, 2),
    risk_score NUMERIC(5, 2),
    risk_approved BOOLEAN NOT NULL DEFAULT false,
    is_consensus BOOLEAN NOT NULL DEFAULT false,
    agent_outputs JSONB NOT NULL DEFAULT '{}',
    rationale TEXT,
    is_executed BOOLEAN NOT NULL DEFAULT false,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_signals_symbol ON signals(symbol);
CREATE INDEX idx_signals_created_at ON signals(created_at DESC);
CREATE INDEX idx_signals_consensus ON signals(is_consensus) WHERE is_consensus = true;

-- ===========================================================================
-- TRADE HISTORY
-- ===========================================================================

CREATE TABLE trade_history (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    signal_id UUID REFERENCES signals(id),
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity NUMERIC(20, 8) NOT NULL,
    entry_price NUMERIC(20, 8) NOT NULL,
    exit_price NUMERIC(20, 8),
    entry_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    exit_at TIMESTAMPTZ,
    pnl NUMERIC(20, 8),
    pnl_pct NUMERIC(10, 4),
    roi_pct NUMERIC(10, 4),
    is_closed BOOLEAN NOT NULL DEFAULT false,
    strategy_name VARCHAR(100),
    agent_rationale JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_trade_history_account_id ON trade_history(account_id);
CREATE INDEX idx_trade_history_symbol ON trade_history(symbol);
CREATE INDEX idx_trade_history_created_at ON trade_history(created_at DESC);

-- ===========================================================================
-- JOURNAL
-- ===========================================================================

CREATE TABLE journal (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    trade_id UUID REFERENCES trade_history(id) ON DELETE CASCADE,
    entry_type VARCHAR(30) NOT NULL
        CHECK (entry_type IN ('trade_opened', 'trade_closed', 'mistake', 'lesson',
                              'reflection', 'strategy_update', 'system_note')),
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    sentiment VARCHAR(10) CHECK (sentiment IN ('positive', 'negative', 'neutral')),
    mistakes_detected JSONB DEFAULT '[]',
    lessons_learned JSONB DEFAULT '[]',
    tags TEXT[] DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_journal_trade_id ON journal(trade_id);
CREATE INDEX idx_journal_entry_type ON journal(entry_type);
CREATE INDEX idx_journal_created_at ON journal(created_at DESC);

-- ===========================================================================
-- STRATEGIES
-- ===========================================================================

CREATE TABLE strategies (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name VARCHAR(100) NOT NULL,
    description TEXT,
    strategy_type VARCHAR(30) NOT NULL
        CHECK (strategy_type IN ('momentum', 'mean_reversion', 'trend_following',
                                 'arbitrage', 'grid', 'dca', 'ml', 'custom')),
    config JSONB NOT NULL DEFAULT '{}',
    parameters JSONB NOT NULL DEFAULT '{}',
    version INT NOT NULL DEFAULT 1,
    status VARCHAR(20) NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'backtesting', 'paper_trading', 'live_trading', 'paused', 'archived')),
    paper_trade_started_at TIMESTAMPTZ,
    paper_trade_closed_trades INT NOT NULL DEFAULT 0,
    live_trading_enabled BOOLEAN NOT NULL DEFAULT false,
    min_paper_trades_required INT NOT NULL DEFAULT 50,
    min_paper_days_required INT NOT NULL DEFAULT 30,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===========================================================================
-- AGENT LOGS
-- ===========================================================================

CREATE TABLE agent_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL DEFAULT uuid_generate_v4(),
    agent_name VARCHAR(50) NOT NULL,
    model_used VARCHAR(100) NOT NULL,
    model_chain TEXT[] NOT NULL DEFAULT '{}',
    input_schema JSONB,
    output_schema JSONB,
    input_data JSONB,
    output_data JSONB,
    latency_ms INT,
    token_count INT,
    success BOOLEAN NOT NULL,
    error_type VARCHAR(50),
    error_message TEXT,
    retry_count INT NOT NULL DEFAULT 0,
    circuit_breaker_tripped BOOLEAN NOT NULL DEFAULT false,
    degraded_mode BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_agent_logs_agent_name ON agent_logs(agent_name);
CREATE INDEX idx_agent_logs_session_id ON agent_logs(session_id);
CREATE INDEX idx_agent_logs_created_at ON agent_logs(created_at DESC);
CREATE INDEX idx_agent_logs_failures ON agent_logs(success) WHERE success = false;

-- ===========================================================================
-- MEMORIES (metadata table — vector storage lives in ChromaDB)
-- ===========================================================================

CREATE TABLE memories (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chroma_id VARCHAR(100),
    memory_type VARCHAR(30) NOT NULL
        CHECK (memory_type IN ('trade', 'mistake', 'strategy', 'pattern',
                               'market_regime', 'lesson', 'agent_output', 'user_preference')),
    content TEXT NOT NULL,
    embedding_model VARCHAR(100),
    metadata JSONB NOT NULL DEFAULT '{}',
    importance_score NUMERIC(3, 1) CHECK (importance_score >= 0 AND importance_score <= 10),
    is_consolidated BOOLEAN NOT NULL DEFAULT false,
    consolidated_into UUID REFERENCES memories(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_memories_type ON memories(memory_type);
CREATE INDEX idx_memories_importance ON memories(importance_score DESC)
    WHERE importance_score IS NOT NULL;

-- ===========================================================================
-- MARKET DATA
-- ===========================================================================

CREATE TABLE market_data (
    id BIGSERIAL PRIMARY KEY,
    symbol VARCHAR(20) NOT NULL,
    source VARCHAR(30) NOT NULL
        CHECK (source IN ('yahoo', 'coingecko', 'binance', 'alpha_vantage', 'polygon')),
    interval VARCHAR(10) NOT NULL
        CHECK (interval IN ('1m', '5m', '15m', '30m', '1h', '4h', '1d', '1w', '1mo')),
    timestamp TIMESTAMPTZ NOT NULL,
    open NUMERIC(20, 8) NOT NULL,
    high NUMERIC(20, 8) NOT NULL,
    low NUMERIC(20, 8) NOT NULL,
    close NUMERIC(20, 8) NOT NULL,
    volume NUMERIC(30, 8) NOT NULL DEFAULT 0,
    vwap NUMERIC(20, 8),
    trades_count INT,
    additional_metrics JSONB DEFAULT '{}'
);

CREATE UNIQUE INDEX idx_market_data_unique
    ON market_data(symbol, source, interval, timestamp);
CREATE INDEX idx_market_data_lookup
    ON market_data(symbol, interval, timestamp DESC);

-- ===========================================================================
-- METRICS (Prometheus-compatible metric store)
-- ===========================================================================

CREATE TABLE metrics (
    id BIGSERIAL PRIMARY KEY,
    metric_name VARCHAR(100) NOT NULL,
    metric_type VARCHAR(20) NOT NULL
        CHECK (metric_type IN ('gauge', 'counter', 'histogram', 'summary')),
    value DOUBLE PRECISION NOT NULL,
    labels JSONB DEFAULT '{}',
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_metrics_name ON metrics(metric_name);
CREATE INDEX idx_metrics_recorded_at ON metrics(recorded_at DESC);
CREATE INDEX idx_metrics_lookup ON metrics(metric_name, recorded_at DESC);

-- ===========================================================================
-- ALERTS
-- ===========================================================================

CREATE TABLE alerts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    alert_type VARCHAR(30) NOT NULL
        CHECK (alert_type IN ('risk_breach', 'drawdown_limit', 'model_failure', 'system_error',
                              'trade_rejected', 'kill_switch_triggered', 'consensus_failure',
                              'data_ingestion_error', 'performance_warning', 'info')),
    severity VARCHAR(10) NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low')),
    title VARCHAR(255) NOT NULL,
    message TEXT NOT NULL,
    details JSONB DEFAULT '{}',
    is_acknowledged BOOLEAN NOT NULL DEFAULT false,
    acknowledged_by UUID REFERENCES users(id),
    acknowledged_at TIMESTAMPTZ,
    source VARCHAR(50),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_alerts_type ON alerts(alert_type);
CREATE INDEX idx_alerts_severity ON alerts(severity);
CREATE INDEX idx_alerts_created_at ON alerts(created_at DESC);
CREATE INDEX idx_alerts_unacknowledged ON alerts(is_acknowledged) WHERE is_acknowledged = false;

-- ===========================================================================
-- RISK METRICS
-- ===========================================================================

CREATE TABLE risk_metrics (
    id BIGSERIAL PRIMARY KEY,
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    portfolio_id UUID REFERENCES portfolio(id),
    var_95 NUMERIC(12, 4),
    var_99 NUMERIC(12, 4),
    sharpe_ratio NUMERIC(10, 4),
    sortino_ratio NUMERIC(10, 4),
    max_drawdown_pct NUMERIC(10, 4),
    current_drawdown_pct NUMERIC(10, 4),
    volatility NUMERIC(10, 4),
    beta NUMERIC(10, 4),
    correlation_matrix JSONB,
    exposure_by_asset JSONB,
    concentration_pct NUMERIC(5, 2),
    margin_used NUMERIC(20, 8),
    leverage NUMERIC(10, 4),
    risk_score NUMERIC(5, 2) CHECK (risk_score >= 0 AND risk_score <= 100),
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_risk_metrics_account_id ON risk_metrics(account_id);
CREATE INDEX idx_risk_metrics_computed_at ON risk_metrics(computed_at DESC);

-- ===========================================================================
-- BACKTESTS
-- ===========================================================================

CREATE TABLE backtests (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID REFERENCES strategies(id) ON DELETE SET NULL,
    strategy_name VARCHAR(100) NOT NULL,
    strategy_config JSONB NOT NULL DEFAULT '{}',
    symbols TEXT[] NOT NULL,
    date_from DATE NOT NULL,
    date_to DATE NOT NULL,
    initial_capital NUMERIC(20, 8) NOT NULL,
    final_value NUMERIC(20, 8),
    total_return_pct NUMERIC(10, 4),
    sharpe_ratio NUMERIC(10, 4),
    sortino_ratio NUMERIC(10, 4),
    win_rate NUMERIC(5, 2),
    profit_factor NUMERIC(10, 4),
    max_drawdown_pct NUMERIC(10, 4),
    total_trades INT,
    winning_trades INT,
    losing_trades INT,
    expectancy NUMERIC(10, 4),
    recovery_factor NUMERIC(10, 4),
    results_json JSONB,
    agent_summary JSONB,
    status VARCHAR(20) NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'running', 'completed', 'failed')),
    error_message TEXT,
    created_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE INDEX idx_backtests_strategy_id ON backtests(strategy_id);
CREATE INDEX idx_backtests_status ON backtests(status);
CREATE INDEX idx_backtests_created_at ON backtests(created_at DESC);

-- ===========================================================================
-- PAPER TRADES
-- ===========================================================================

CREATE TABLE paper_trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    strategy_id UUID REFERENCES strategies(id) ON DELETE SET NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity NUMERIC(20, 8) NOT NULL,
    entry_price NUMERIC(20, 8) NOT NULL,
    exit_price NUMERIC(20, 8),
    entry_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    exit_at TIMESTAMPTZ,
    pnl NUMERIC(20, 8),
    pnl_pct NUMERIC(10, 4),
    roi_pct NUMERIC(10, 4),
    is_closed BOOLEAN NOT NULL DEFAULT false,
    signal_id UUID REFERENCES signals(id),
    agent_rationale JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_paper_trades_strategy_id ON paper_trades(strategy_id);
CREATE INDEX idx_paper_trades_symbol ON paper_trades(symbol);
CREATE INDEX idx_paper_trades_created_at ON paper_trades(created_at DESC);

-- ===========================================================================
-- LIVE TRADES
-- ===========================================================================

CREATE TABLE live_trades (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    account_id UUID NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    strategy_id UUID REFERENCES strategies(id) ON DELETE SET NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL CHECK (side IN ('buy', 'sell')),
    quantity NUMERIC(20, 8) NOT NULL,
    entry_price NUMERIC(20, 8) NOT NULL,
    exit_price NUMERIC(20, 8),
    entry_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    exit_at TIMESTAMPTZ,
    pnl NUMERIC(20, 8),
    pnl_pct NUMERIC(10, 4),
    is_closed BOOLEAN NOT NULL DEFAULT false,
    approval_mode VARCHAR(20) NOT NULL DEFAULT 'human_approval'
        CHECK (approval_mode IN ('human_approval', 'semi_autonomous', 'full_autonomous')),
    human_approved BOOLEAN NOT NULL DEFAULT false,
    approved_by UUID REFERENCES users(id),
    approved_at TIMESTAMPTZ,
    kill_switch_active BOOLEAN NOT NULL DEFAULT false,
    exchange_order_id VARCHAR(100),
    signal_id UUID REFERENCES signals(id),
    agent_rationale JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_live_trades_account_id ON live_trades(account_id);
CREATE INDEX idx_live_trades_symbol ON live_trades(symbol);
CREATE INDEX idx_live_trades_created_at ON live_trades(created_at DESC);
CREATE INDEX idx_live_trades_open ON live_trades(is_closed) WHERE is_closed = false;

-- ===========================================================================
-- TRIGGERS — auto-update updated_at columns
-- ===========================================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_accounts_updated_at
    BEFORE UPDATE ON accounts
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_portfolio_updated_at
    BEFORE UPDATE ON portfolio
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_positions_updated_at
    BEFORE UPDATE ON positions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_orders_updated_at
    BEFORE UPDATE ON orders
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_trade_history_updated_at
    BEFORE UPDATE ON trade_history
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_strategies_updated_at
    BEFORE UPDATE ON strategies
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_live_trades_updated_at
    BEFORE UPDATE ON live_trades
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER trg_paper_trades_updated_at
    BEFORE UPDATE ON paper_trades
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
