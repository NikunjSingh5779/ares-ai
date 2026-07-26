"""Supabase Backend Service — optional hosted database and auth.

Provides Supabase as an alternative backend for authentication and data
storage alongside ARES's existing PostgreSQL/SQLAlchemy setup.

Supabase features integrated:
- **Auth**: Email/password, OAuth, magic link authentication
- **Database**: Managed PostgreSQL with auto-generated REST API
- **Realtime**: WebSocket-based subscriptions for live data
- **Storage**: File/asset storage for chart images, reports

This service is OPTIONAL — it gracefully returns None when supabase-py
is not installed. All features check for availability at runtime.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supabase Client Singleton
# ---------------------------------------------------------------------------

_supabase_client: Any = None


class SupabaseService:
    """Supabase integration for ARES AI.

    Provides auth, database, and realtime features backed by Supabase.
    All methods check for availability and return None when not configured.

    Usage:
        svc = SupabaseService()
        if svc.available:
            user = await svc.sign_in(email, password)
    """

    def __init__(self) -> None:
        self._client: Any = None
        self._available: bool | None = None  # None = not checked

    @property
    def available(self) -> bool:
        """Check if Supabase is available and configured."""
        if self._available is None:
            self._check_availability()
        return self._available  # type: ignore[return-value]

    def _check_availability(self) -> None:
        """Check if supabase-py is installed and env vars are set."""
        try:
            import supabase  # type: ignore[import-untyped]  # noqa: F401

            url = os.getenv("SUPABASE_URL", "")
            key = os.getenv("SUPABASE_KEY", "")
            self._available = bool(url and key)
            if not self._available:
                logger.info(
                    "Supabase not configured: set SUPABASE_URL and SUPABASE_KEY env vars"
                )
        except ImportError:
            self._available = False
            logger.debug("supabase-py not installed")

    def _get_client(self) -> Any:
        """Lazy-init the Supabase client."""
        if self._client is not None:
            return self._client

        if not self.available:
            return None

        try:
            from supabase import create_client  # type: ignore[import-untyped]

            url = os.getenv("SUPABASE_URL", "")
            key = os.getenv("SUPABASE_KEY", "")
            self._client = create_client(url, key)
            logger.info("Supabase client initialized")
            return self._client
        except Exception as e:
            logger.error(f"Failed to initialize Supabase client: {e}")
            self._available = False
            return None

    # ------------------------------------------------------------------
    # Auth Methods
    # ------------------------------------------------------------------

    async def sign_up(self, email: str, password: str, metadata: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """Register a new user via Supabase Auth."""
        client = self._get_client()
        if not client:
            return None
        try:
            # sync call wrapped for async context
            resp = client.auth.sign_up({"email": email, "password": password, "options": {"data": metadata or {}}})
            return {"user_id": resp.user.id, "email": resp.user.email, "created_at": resp.user.created_at}  # type: ignore[union-attr]
        except Exception as e:
            logger.error(f"Supabase sign_up failed: {e}")
            return None

    async def sign_in(self, email: str, password: str) -> dict[str, Any] | None:
        """Sign in with email and password."""
        client = self._get_client()
        if not client:
            return None
        try:
            resp = client.auth.sign_in_with_password({"email": email, "password": password})
            return {"user_id": resp.user.id, "email": resp.user.email, "access_token": resp.session.access_token}  # type: ignore[union-attr]
        except Exception as e:
            logger.error(f"Supabase sign_in failed: {e}")
            return None

    async def sign_out(self) -> bool:
        """Sign out the current user."""
        client = self._get_client()
        if not client:
            return False
        try:
            client.auth.sign_out()
            return True
        except Exception:
            return False

    async def get_user(self) -> dict[str, Any] | None:
        """Get the current authenticated user."""
        client = self._get_client()
        if not client:
            return None
        try:
            user = client.auth.get_user()
            return {"id": user.user.id, "email": user.user.email}  # type: ignore[union-attr]
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Database Methods
    # ------------------------------------------------------------------

    async def insert(self, table: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Insert a row into a Supabase table."""
        client = self._get_client()
        if not client:
            return None
        try:
            resp = client.table(table).insert(data).execute()
            return resp.data  # type: ignore[return-value]
        except Exception as e:
            logger.error(f"Supabase insert failed: {e}")
            return None

    async def select(
        self,
        table: str,
        columns: str = "*",
        filters: dict[str, Any] | None = None,
        limit: int = 100,
        order: str | None = None,
    ) -> list[dict[str, Any]] | None:
        """Select rows from a Supabase table."""
        client = self._get_client()
        if not client:
            return None
        try:
            query = client.table(table).select(columns)
            if filters:
                for key, value in filters.items():
                    query = query.eq(key, value)
            if order:
                query = query.order(order)
            resp = query.limit(limit).execute()
            return resp.data  # type: ignore[return-value]
        except Exception as e:
            logger.error(f"Supabase select failed: {e}")
            return None

    async def update(
        self,
        table: str,
        filters: dict[str, Any],
        data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Update rows in a Supabase table matching filters."""
        client = self._get_client()
        if not client:
            return None
        try:
            query = client.table(table).update(data)
            for key, value in filters.items():
                query = query.eq(key, value)
            resp = query.execute()
            return resp.data  # type: ignore[return-value]
        except Exception as e:
            logger.error(f"Supabase update failed: {e}")
            return None

    async def delete(self, table: str, filters: dict[str, Any]) -> bool:
        """Delete rows from a Supabase table matching filters."""
        client = self._get_client()
        if not client:
            return False
        try:
            query = client.table(table).delete()
            for key, value in filters.items():
                query = query.eq(key, value)
            query.execute()
            return True
        except Exception as e:
            logger.error(f"Supabase delete failed: {e}")
            return False

    # ------------------------------------------------------------------
    # Realtime
    # ------------------------------------------------------------------

    def subscribe(
        self,
        channel: str,
        table: str,
        event: str = "*",
        callback: Any = None,
    ) -> Any | None:
        """Subscribe to realtime changes on a table.

        Args:
            channel: Channel name (e.g., "trades-updates").
            table: Table to watch.
            event: Event type ("INSERT", "UPDATE", "DELETE", or "*").
            callback: Function to call with each change event.

        Returns:
            Subscription object or None if not available.
        """
        client = self._get_client()
        if not client or not callback:
            return None
        try:
            sub = client.channel(channel).on("postgres_changes", {"event": event, "schema": "public", "table": table}, callback).subscribe()
            return sub
        except Exception as e:
            logger.error(f"Supabase subscribe failed: {e}")
            return None

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------

    async def upload_file(self, bucket: str, path: str, file_data: bytes, content_type: str = "application/octet-stream") -> str | None:
        """Upload a file to Supabase Storage.

        Args:
            bucket: Storage bucket name.
            path: File path within bucket.
            file_data: File content as bytes.
            content_type: MIME type.

        Returns:
            Public URL of the uploaded file, or None on failure.
        """
        client = self._get_client()
        if not client:
            return None
        try:
            resp = client.storage.from_(bucket).upload(path, file_data, {"content-type": content_type})
            # Get public URL
            public_url = client.storage.from_(bucket).get_public_url(path)
            return public_url  # type: ignore[return-value]
        except Exception as e:
            logger.error(f"Supabase upload failed: {e}")
            return None


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_supabase_service() -> SupabaseService | None:
    """Get the Supabase service if available, otherwise None."""
    try:
        svc = SupabaseService()
        return svc if svc.available else None
    except Exception as e:
        logger.debug(f"Supabase service not available: {e}")
        return None
