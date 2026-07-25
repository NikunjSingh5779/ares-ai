"""SQLAlchemy ORM Models for ARES-AI."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Numeric, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.db.base import Base


def _utcnow() -> datetime:
    """Return the current UTC datetime."""
    return datetime.now(UTC)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="user", nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    accounts: Mapped[list[Account]] = relationship("Account", back_populates="user", cascade="all, delete-orphan")


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "exchange", "account_name", name="accounts_user_id_exchange_account_name_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    account_name: Mapped[str] = mapped_column(String(100), nullable=False)
    api_key_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    api_secret_encrypted: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    trading_mode: Mapped[str] = mapped_column(String(20), default="human_approval", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    user: Mapped[User] = relationship("User", back_populates="accounts")
    portfolios: Mapped[list[Portfolio]] = relationship(
        "Portfolio", back_populates="account", cascade="all, delete-orphan"
    )
    orders: Mapped[list[Order]] = relationship("Order", back_populates="account", cascade="all, delete-orphan")


class Portfolio(Base):
    __tablename__ = "portfolio"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    total_value: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    cash_balance: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    invested_amount: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    realized_pnl: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    roi_pct: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    max_drawdown_pct: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="USD", nullable=False)
    last_rebalanced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    account: Mapped[Account] = relationship("Account", back_populates="portfolios")
    positions: Mapped[list[Position]] = relationship(
        "Position", back_populates="portfolio", cascade="all, delete-orphan"
    )
    unrealized_pnl_pct: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)


class Position(Base):
    __tablename__ = "positions"
    __table_args__ = (
        Index("idx_positions_portfolio_id", "portfolio_id"),
        Index("idx_positions_symbol", "symbol"),
        Index("idx_positions_open", "is_open", postgresql_where="is_open = true"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolio.id", ondelete="CASCADE"), nullable=False)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    asset_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    current_price: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    market_value: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    unrealized_pnl: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    unrealized_pnl_pct: Mapped[float] = mapped_column(Numeric(10, 4), default=0, nullable=False)
    stop_loss: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    take_profit: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    strategy_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_open: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    portfolio: Mapped[Portfolio] = relationship("Portfolio", back_populates="positions")
    orders: Mapped[list[Order]] = relationship("Order", back_populates="position")


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index("idx_orders_account_id", "account_id"),
        Index("idx_orders_status", "status"),
        Index("idx_orders_created_at", "created_at", postgresql_ops={"created_at": "DESC"}),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    position_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("positions.id"), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    order_type: Mapped[str] = mapped_column(String(20), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    price: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    stop_price: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    exchange_order_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    filled_quantity: Mapped[float] = mapped_column(Numeric(20, 8), default=0, nullable=False)
    avg_fill_price: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    agent_rationale: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    account: Mapped[Account] = relationship("Account", back_populates="orders")
    position: Mapped[Position | None] = relationship("Position", back_populates="orders")


class TradeHistory(Base):
    __tablename__ = "trade_history"
    __table_args__ = (
        Index("idx_trade_history_account_id", "account_id"),
        Index("idx_trade_history_symbol", "symbol"),
        Index("idx_trade_history_created_at", "created_at", postgresql_ops={"created_at": "DESC"}),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False)
    signal_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    symbol: Mapped[str] = mapped_column(String(20), nullable=False)
    side: Mapped[str] = mapped_column(String(10), nullable=False)
    quantity: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    entry_price: Mapped[float] = mapped_column(Numeric(20, 8), nullable=False)
    exit_price: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    entry_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    exit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pnl: Mapped[float | None] = mapped_column(Numeric(20, 8), nullable=True)
    pnl_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    roi_pct: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    is_closed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    strategy_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    agent_rationale: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
