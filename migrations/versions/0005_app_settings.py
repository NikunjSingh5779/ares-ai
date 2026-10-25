"""Add the singleton application-settings row.

Revision ID: 0005_app_settings
Revises: 0004_role_hierarchy
Create Date: 2026-10-22

Dashboard preferences need a durable home that is not the trading ledger. The
table holds one JSON document and no safety limits: position caps, risk
ceilings, confidence thresholds, drawdown limits, and promotion gates remain in
code/configuration. Statements are idempotent because a fresh database runs the
current ``database/schema.sql`` from revision ``0001``.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0005_app_settings"
down_revision: str | None = "0004_role_hierarchy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the one-row settings table, seed it, and add its updated_at trigger."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            id SMALLINT PRIMARY KEY CHECK (id = 1),
            preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("INSERT INTO app_settings (id) VALUES (1) ON CONFLICT (id) DO NOTHING")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_trigger WHERE tgname = 'trg_app_settings_updated_at'
            ) THEN
                CREATE TRIGGER trg_app_settings_updated_at
                    BEFORE UPDATE ON app_settings
                    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Drop the dashboard-preferences table."""
    op.execute("DROP TABLE IF EXISTS app_settings CASCADE")
