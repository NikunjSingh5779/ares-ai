"""Tests for database connection and session management."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestGetSession:
    """get_session async generator coverage."""

    @pytest.mark.asyncio
    async def test_get_session_success_path(self) -> None:
        """Verify the happy path: yield session, commit, close."""
        from collections.abc import AsyncGenerator

        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.commit = AsyncMock()
        mock_session.close = AsyncMock()

        async_session_factory = MagicMock(return_value=mock_session)

        with patch("database.connection.async_session_factory", async_session_factory):
            from database.connection import get_session

            gen = get_session()
            assert isinstance(gen, AsyncGenerator)

            session = await gen.__anext__()
            assert session is mock_session

            with pytest.raises(StopAsyncIteration):
                await gen.__anext__()

            mock_session.commit.assert_awaited_once()
            mock_session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_session_rollback_on_exception(self) -> None:
        """Verify rollback is called when the session block raises."""
        mock_session = AsyncMock()
        mock_session.__aenter__.return_value = mock_session
        mock_session.commit = AsyncMock()
        mock_session.rollback = AsyncMock()
        mock_session.close = AsyncMock()

        async_session_factory = MagicMock(return_value=mock_session)

        with patch("database.connection.async_session_factory", async_session_factory):
            from database.connection import get_session

            gen = get_session()
            await gen.__anext__()  # yields session

            with pytest.raises(RuntimeError, match="test error"):
                await gen.athrow(RuntimeError("test error"))

            mock_session.rollback.assert_awaited_once()
            mock_session.close.assert_awaited_once()


class TestCheckConnection:
    """check_connection coverage."""

    @pytest.mark.asyncio
    async def test_check_connection_success(self) -> None:
        """verify check_connection returns True when DB is reachable."""
        mock_conn = AsyncMock()
        mock_conn.__aenter__.return_value = mock_conn
        mock_conn.execute = AsyncMock()

        mock_engine = MagicMock()
        mock_engine.connect.return_value = mock_conn

        with patch("database.connection.engine", mock_engine):
            from database.connection import check_connection

            result = await check_connection()
            assert result is True
            mock_conn.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_check_connection_failure(self) -> None:
        """verify check_connection returns False on exception."""
        mock_engine = MagicMock()
        mock_engine.connect.side_effect = RuntimeError("Connection refused")

        with patch("database.connection.engine", mock_engine):
            from database.connection import check_connection

            result = await check_connection()
            assert result is False
