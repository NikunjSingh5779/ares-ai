from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AccountBase(BaseModel):
    exchange: str
    account_name: str
    trading_mode: str = "human_approval"


class AccountCreate(AccountBase):
    api_key: str
    api_secret: str


class AccountResponse(AccountBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime


class PortfolioBase(BaseModel):
    total_value: float
    cash_balance: float
    invested_amount: float
    unrealized_pnl: float
    realized_pnl: float
    roi_pct: float
    max_drawdown_pct: float
    currency: str = "USD"


class PortfolioResponse(PortfolioBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    account_id: UUID
    last_rebalanced_at: datetime | None
    created_at: datetime
    updated_at: datetime


class PositionBase(BaseModel):
    symbol: str
    asset_type: str
    quantity: float
    entry_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    unrealized_pnl_pct: float
    stop_loss: float | None = None
    take_profit: float | None = None
    strategy_name: str | None = None
    is_open: bool = True


class PositionResponse(PositionBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    portfolio_id: UUID
    opened_at: datetime
    closed_at: datetime | None
    created_at: datetime
    updated_at: datetime


class OrderBase(BaseModel):
    symbol: str
    side: str
    order_type: str
    quantity: float
    price: float | None = None
    stop_price: float | None = None
    strategy_name: str | None = None


class OrderResponse(OrderBase):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    account_id: UUID
    position_id: UUID | None = None
    status: str
    exchange_order_id: str | None = None
    filled_quantity: float
    average_fill_price: float
    fee: float
    fee_currency: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime
