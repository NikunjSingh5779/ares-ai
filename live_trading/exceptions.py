"""Live trading exceptions — type hierarchy for all live trading errors."""


class LiveTradingError(Exception):
    """Base exception for all live trading errors."""


class KillSwitchTrippedError(LiveTradingError):
    """Raised when a trade is attempted while the kill switch is active."""


class PromotionGateError(LiveTradingError):
    """Raised when a live trade is attempted before the paper record meets requirements."""


class ExchangeConnectionError(LiveTradingError):
    """Raised when the exchange is unreachable or authentication fails."""


class ModeError(LiveTradingError):
    """Raised when an operation is invalid for the current trading mode."""


class OrderRejectedError(LiveTradingError):
    """Raised when the exchange rejects an order."""
