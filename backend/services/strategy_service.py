"""Persistence for draft strategies.

The table predates this service; this module only exposes the safe draft surface.
Status, live enablement, and promotion counters are never written here.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.schemas.strategy import (
    StrategyConfig,
    StrategyCreate,
    StrategyParameters,
    StrategyResponse,
    StrategyUpdate,
)

logger = logging.getLogger("ares.strategies")

_EDITABLE_STATUSES = frozenset({"draft", "paused"})

_COLUMNS = """
    id, name, description, strategy_type, config, parameters, version, status,
    paper_trade_closed_trades, live_trading_enabled, created_at, updated_at
"""

_SELECT_ALL = text(
    f"""
    SELECT {_COLUMNS}
    FROM strategies
    ORDER BY updated_at DESC, created_at DESC
    LIMIT :limit
    """
)

_SELECT_ONE = text(
    f"""
    SELECT {_COLUMNS}
    FROM strategies
    WHERE id = :strategy_id
    """
)

_INSERT = text(
    f"""
    INSERT INTO strategies (
        name, description, strategy_type, config, parameters
    )
    VALUES (
        :name, :description, :strategy_type,
        CAST(:config AS JSONB), CAST(:parameters AS JSONB)
    )
    RETURNING {_COLUMNS}
    """
)

_UPDATE = text(
    f"""
    UPDATE strategies
    SET name = :name,
        description = :description,
        strategy_type = :strategy_type,
        config = CAST(:config AS JSONB),
        parameters = CAST(:parameters AS JSONB),
        version = version + 1,
        updated_at = NOW()
    WHERE id = :strategy_id
      AND status IN ('draft', 'paused')
    RETURNING {_COLUMNS}
    """
)


class StrategyNotFoundError(Exception):
    """The requested strategy does not exist."""


class StrategyNotEditableError(Exception):
    """A strategy outside draft/paused cannot be edited through this surface."""


def _decode_json(value: Any) -> dict[str, Any]:
    """Decode a JSONB value from PostgreSQL or a test double."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            logger.warning("Stored strategy JSON is invalid; using an empty object")
            return {}
    return value if isinstance(value, dict) else {}


def _row_to_response(row: Any) -> StrategyResponse:
    """Convert a database row into the public response model."""
    return StrategyResponse(
        id=row.id,
        name=row.name,
        description=row.description or "",
        strategy_type=row.strategy_type,
        config=StrategyConfig.model_validate(_decode_json(row.config)),
        parameters=StrategyParameters.model_validate(_decode_json(row.parameters)),
        version=row.version,
        status=row.status,
        paper_trade_closed_trades=getattr(row, "paper_trade_closed_trades", 0),
        live_trading_enabled=getattr(row, "live_trading_enabled", False),
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _params_for_create(data: StrategyCreate) -> dict[str, Any]:
    """Serialize a create payload for PostgreSQL."""
    return {
        "name": data.name,
        "description": data.description,
        "strategy_type": data.strategy_type,
        "config": json.dumps(data.config.model_dump()),
        "parameters": json.dumps(data.parameters.model_dump()),
    }


async def list_strategies(
    session: AsyncSession,
    limit: int = 50,
) -> list[StrategyResponse]:
    """Return recent strategies, newest first."""
    result = await session.execute(_SELECT_ALL, {"limit": max(1, min(limit, 100))})
    return [_row_to_response(row) for row in result.fetchall()]


async def get_strategy(
    session: AsyncSession,
    strategy_id: UUID,
) -> StrategyResponse | None:
    """Return one strategy, or ``None`` when it does not exist."""
    result = await session.execute(_SELECT_ONE, {"strategy_id": strategy_id})
    row = result.first()
    return _row_to_response(row) if row is not None else None


async def create_strategy(
    session: AsyncSession,
    data: StrategyCreate,
) -> StrategyResponse:
    """Create a draft strategy and return the row PostgreSQL accepted."""
    result = await session.execute(_INSERT, _params_for_create(data))
    row = result.first()
    if row is None:
        raise RuntimeError("Strategy insert returned no row")
    return _row_to_response(row)


async def update_strategy(
    session: AsyncSession,
    strategy_id: UUID,
    data: StrategyUpdate,
) -> StrategyResponse:
    """Update a draft or paused strategy, preserving server-owned fields.

    A version bump makes it clear that a saved strategy is a new revision. The
    caller can never set status, live enablement, or promotion counters.
    """
    current = await get_strategy(session, strategy_id)
    if current is None:
        raise StrategyNotFoundError
    if current.status not in _EDITABLE_STATUSES:
        raise StrategyNotEditableError

    name = data.name if data.name is not None else current.name
    description = data.description if data.description is not None else current.description
    strategy_type = data.strategy_type if data.strategy_type is not None else current.strategy_type
    config = data.config if data.config is not None else current.config
    parameters = data.parameters if data.parameters is not None else current.parameters

    result = await session.execute(
        _UPDATE,
        {
            "strategy_id": strategy_id,
            "name": name,
            "description": description,
            "strategy_type": strategy_type,
            "config": json.dumps(config.model_dump()),
            "parameters": json.dumps(parameters.model_dump()),
        },
    )
    row = result.first()
    if row is None:
        # The row could have been deleted or promoted between the read and the update.
        if await get_strategy(session, strategy_id) is None:
            raise StrategyNotFoundError
        raise StrategyNotEditableError
    return _row_to_response(row)
