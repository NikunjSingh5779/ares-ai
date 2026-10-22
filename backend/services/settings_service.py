"""Durable dashboard preferences.

The ``app_settings`` table is a one-row JSON document. Only non-safety
preferences live here; trading limits are code/configuration and are exposed
read-only by the settings router. A corrupt or missing row falls back to the
defaults instead of breaking the dashboard.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.schemas.settings import DashboardPreferences

logger = logging.getLogger("ares.settings")

DEFAULT_PREFERENCES = DashboardPreferences()

_SELECT_PREFERENCES = text("SELECT preferences FROM app_settings WHERE id = 1")

_UPSERT_PREFERENCES = text(
    """
    INSERT INTO app_settings (id, preferences)
    VALUES (1, CAST(:preferences AS JSONB))
    ON CONFLICT (id) DO UPDATE
        SET preferences = EXCLUDED.preferences,
            updated_at = NOW()
    RETURNING preferences
    """
)


def _decode_preferences(value: Any) -> DashboardPreferences:
    """Turn a JSONB value into validated preferences, falling back to defaults."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            logger.warning("Stored dashboard preferences are not valid JSON; using defaults")
            return DEFAULT_PREFERENCES.model_copy()

    if not isinstance(value, dict):
        if value is not None:
            logger.warning("Stored dashboard preferences are not an object; using defaults")
        return DEFAULT_PREFERENCES.model_copy()

    try:
        # Merge over defaults so a preference added in a later release gets its
        # default value without requiring a data migration.
        return DashboardPreferences.model_validate({**DEFAULT_PREFERENCES.model_dump(), **value})
    except ValidationError:
        logger.warning("Stored dashboard preferences are invalid; using defaults", exc_info=True)
        return DEFAULT_PREFERENCES.model_copy()


async def load_preferences(session: AsyncSession) -> DashboardPreferences:
    """Read the persisted preferences, or the defaults before the first save."""
    result = await session.execute(_SELECT_PREFERENCES)
    row = result.first()
    if row is None:
        return DEFAULT_PREFERENCES.model_copy()
    return _decode_preferences(row[0])


async def save_preferences(
    session: AsyncSession,
    preferences: DashboardPreferences,
) -> DashboardPreferences:
    """Persist preferences and return the value PostgreSQL accepted."""
    result = await session.execute(
        _UPSERT_PREFERENCES,
        {"preferences": json.dumps(preferences.model_dump())},
    )
    row = result.first()
    if row is None:
        raise RuntimeError("Settings upsert returned no row")
    return _decode_preferences(row[0])
