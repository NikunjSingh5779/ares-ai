"""Persist paper borrow/funding carry costs.

Revision ID: 0007_carry_costs
Revises: 0006_improvement_history
Create Date: 2026-11-03

Paper positions previously modelled commission and slippage only. These
columns store accrued borrow (short) or funding (long) cost and the timestamp
used for the next accrual. A fresh database runs the current
``database/schema.sql`` from revision ``0001``, so the statements are
idempotent.

``last_accrual_at`` is backfilled from ``opened_at`` for existing rows so a
restart cannot replay the whole holding period as one charge.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_carry_costs"
down_revision: str | None = "0006_improvement_history"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add carry-cost columns and backfill the accrual clock."""
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS carry_cost NUMERIC(20, 8) NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE positions ADD COLUMN IF NOT EXISTS last_accrual_at TIMESTAMPTZ")
    op.execute("UPDATE positions SET last_accrual_at = opened_at WHERE last_accrual_at IS NULL")
    op.execute("ALTER TABLE trade_history ADD COLUMN IF NOT EXISTS carry_cost NUMERIC(20, 8) NOT NULL DEFAULT 0")


def downgrade() -> None:
    """Remove the carry-cost columns."""
    op.execute("ALTER TABLE trade_history DROP COLUMN IF EXISTS carry_cost")
    op.execute("ALTER TABLE positions DROP COLUMN IF EXISTS last_accrual_at")
    op.execute("ALTER TABLE positions DROP COLUMN IF EXISTS carry_cost")
