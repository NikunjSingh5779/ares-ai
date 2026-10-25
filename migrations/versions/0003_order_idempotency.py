"""Add client order IDs for paper-order idempotency.

Revision ID: 0003_order_idempotency
Revises: 0002_paper_ledger
Create Date: 2026-10-21

The initial revision executes the current ``database/schema.sql``, so a fresh
database already has the column and index. These statements are therefore
idempotent, while an older database gets the new column and unique index.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0003_order_idempotency"
down_revision: str | None = "0002_paper_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add the client order ID and its per-account uniqueness constraint."""
    op.execute("ALTER TABLE orders ADD COLUMN IF NOT EXISTS client_order_id VARCHAR(100)")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_client_order_id "
        "ON orders(account_id, client_order_id) WHERE client_order_id IS NOT NULL"
    )


def downgrade() -> None:
    """Remove the client order ID index and column."""
    op.execute("DROP INDEX IF EXISTS uq_orders_client_order_id")
    op.execute("ALTER TABLE orders DROP COLUMN IF EXISTS client_order_id")
