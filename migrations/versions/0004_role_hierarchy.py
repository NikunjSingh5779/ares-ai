"""Introduce the viewer/operator role hierarchy.

Revision ID: 0004_role_hierarchy
Revises: 0003_order_idempotency
Create Date: 2026-10-21

P1.6 makes trade execution and live controls role-gated. The old schema only
allowed ``user``/``admin``/``super_admin``. This revision:

* rewrites the legacy ``user`` role to ``operator`` (preserving existing
  access);
* allows ``viewer`` and ``operator``;
* changes the default for new rows to ``viewer`` (fail closed).

The constraint name is discovered from ``pg_constraint`` rather than assumed,
because PostgreSQL auto-names inline checks and a fresh database (``0001``
executes the current ``database/schema.sql``) already has the new definition.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0004_role_hierarchy"
down_revision: str | None = "0003_order_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Replace the role check constraint and migrate legacy ``user`` rows."""
    op.execute(
        """
        DO $$
        DECLARE constraint_name text;
        BEGIN
            FOR constraint_name IN
                SELECT conname
                FROM pg_constraint
                WHERE conrelid = 'users'::regclass
                  AND contype = 'c'
                  AND pg_get_constraintdef(oid) LIKE '%role%'
            LOOP
                EXECUTE format('ALTER TABLE users DROP CONSTRAINT %I', constraint_name);
            END LOOP;
        END $$;
        """
    )
    op.execute("UPDATE users SET role = 'operator' WHERE role = 'user'")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'viewer'")
    op.execute(
        "ALTER TABLE users ADD CONSTRAINT users_role_check "
        "CHECK (role IN ('viewer', 'operator', 'admin', 'super_admin'))"
    )


def downgrade() -> None:
    """Restore the pre-P1.6 role set and fold viewer/operator into ``user``."""
    op.execute("ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check")
    op.execute("UPDATE users SET role = 'user' WHERE role IN ('viewer', 'operator')")
    op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'user'")
    op.execute("ALTER TABLE users ADD CONSTRAINT users_role_check CHECK (role IN ('user', 'admin', 'super_admin'))")
