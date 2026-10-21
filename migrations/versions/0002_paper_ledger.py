"""Add durable paper-ledger fields.

Revision ID: 0002_paper_ledger
Revises: 0001
Create Date: 2026-10-21

The statements are idempotent because the initial revision executes the
current ``database/schema.sql``. A fresh database therefore already has these
columns when this revision runs.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002_paper_ledger"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add long/short, cost, margin, and equity-curve fields."""
    op.execute("ALTER TABLE portfolio ADD COLUMN IF NOT EXISTS initial_capital NUMERIC(20, 8) NOT NULL DEFAULT 100000")
    op.execute("ALTER TABLE portfolio ADD COLUMN IF NOT EXISTS margin_used NUMERIC(20, 8) NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE portfolio ADD COLUMN IF NOT EXISTS equity_curve JSONB NOT NULL DEFAULT '[]'::jsonb")

    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS side VARCHAR(10) NOT NULL DEFAULT 'long'")
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS entry_commission NUMERIC(20, 8) NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS margin NUMERIC(20, 8) NOT NULL DEFAULT 0")

    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_positions_side') THEN
                ALTER TABLE positions
                    ADD CONSTRAINT ck_positions_side CHECK (side IN ('long', 'short'));
            END IF;
        END $$;
        """
    )

    op.execute("ALTER TABLE trade_history ADD COLUMN IF NOT EXISTS position_side VARCHAR(10) NOT NULL DEFAULT 'long'")
    op.execute("ALTER TABLE trade_history ADD COLUMN IF NOT EXISTS entry_commission NUMERIC(20, 8) NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE trade_history ADD COLUMN IF NOT EXISTS exit_commission NUMERIC(20, 8) NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE trade_history ADD COLUMN IF NOT EXISTS exit_reason VARCHAR(30) NOT NULL DEFAULT 'signal'")
    # Older rows predate position_side. trade_history.side is the entry side,
    # so a sell entry is a short. Existing positions cannot be inferred; they
    # are assumed long and must be reconciled manually if they were short.
    op.execute("UPDATE trade_history SET position_side = 'short' WHERE side = 'sell' AND position_side = 'long'")
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_trade_history_position_side') THEN
                ALTER TABLE trade_history
                    ADD CONSTRAINT ck_trade_history_position_side
                    CHECK (position_side IN ('long', 'short'));
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    """Remove the durable paper-ledger fields."""
    op.execute("ALTER TABLE trade_history DROP CONSTRAINT IF EXISTS ck_trade_history_position_side")
    op.execute("ALTER TABLE trade_history DROP COLUMN IF EXISTS exit_reason")
    op.execute("ALTER TABLE trade_history DROP COLUMN IF EXISTS exit_commission")
    op.execute("ALTER TABLE trade_history DROP COLUMN IF EXISTS entry_commission")
    op.execute("ALTER TABLE trade_history DROP COLUMN IF EXISTS position_side")

    op.execute("ALTER TABLE positions DROP CONSTRAINT IF EXISTS ck_positions_side")
    op.execute("ALTER TABLE positions DROP COLUMN IF EXISTS margin")
    op.execute("ALTER TABLE positions DROP COLUMN IF EXISTS entry_commission")
    op.execute("ALTER TABLE positions DROP COLUMN IF EXISTS side")

    op.execute("ALTER TABLE portfolio DROP COLUMN IF EXISTS equity_curve")
    op.execute("ALTER TABLE portfolio DROP COLUMN IF EXISTS margin_used")
    op.execute("ALTER TABLE portfolio DROP COLUMN IF EXISTS initial_capital")
