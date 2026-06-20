"""Base exception hierarchy for ARES AI."""

from __future__ import annotations


class AresError(Exception):
    """Base exception for all ARES AI errors."""


class ConfigurationError(AresError):
    """Raised when system configuration is invalid or missing."""


class DatabaseError(AresError):
    """Raised on database connection or query failures."""


class AgentError(AresError):
    """Base exception for agent-related errors."""


class AgentValidationError(AgentError):
    """Raised when agent input/output schema validation fails."""


class AgentExecutionError(AgentError):
    """Raised when an agent's process() method fails."""


class ModelUnavailableError(AgentError):
    """Raised when all models in an agent's fallback chain are exhausted."""


class CircuitBreakerOpenError(AgentError):
    """Raised when an agent's circuit breaker is tripped (too many failures)."""


class TradingError(AresError):
    """Base exception for trading-related errors."""


class InsufficientCapitalError(TradingError):
    """Raised when there isn't enough capital to execute a trade."""


class RiskCheckFailedError(TradingError):
    """Raised when a trade fails risk validation."""


class ConsensusRejectedError(TradingError):
    """Raised when the consensus engine rejects a signal."""


class KillSwitchEngagedError(TradingError):
    """Raised when the kill switch is active and prevents trading."""


class AuthenticationError(AresError):
    """Raised on authentication failures."""


class RateLimitError(AresError):
    """Raised when API rate limits are exceeded."""


class DataIngestionError(AresError):
    """Raised when market data ingestion fails."""
