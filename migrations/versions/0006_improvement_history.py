"""Persist reflection runs and generated improvement records.

Revision ID: 0006_improvement_history
Revises: 0005_app_settings
Create Date: 2026-10-24

The improvement engine used a process-local list, so trends reset on restart and
the API returned no history in normal operation. These tables keep structured
reflection output and the suggestions derived from it. The journal remains the
human-readable summary; it is not a substitute for these fields.

Statements are idempotent because a fresh database runs the current
``database/schema.sql`` from revision ``0001``.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0006_improvement_history"
down_revision: str | None = "0005_app_settings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create the reflection-run and improvement-record tables."""
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS reflection_runs (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            session_id UUID,
            request_id UUID,
            symbol VARCHAR(30) NOT NULL DEFAULT '',
            evaluation TEXT NOT NULL,
            confidence_accuracy NUMERIC(5, 2) NOT NULL
                CHECK (confidence_accuracy >= 0 AND confidence_accuracy <= 100),
            improvement_suggestions JSONB NOT NULL DEFAULT '[]'::jsonb,
            knowledge_updates JSONB NOT NULL DEFAULT '[]'::jsonb,
            errors JSONB NOT NULL DEFAULT '[]'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_reflection_runs_created_at ON reflection_runs(created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_reflection_runs_symbol ON reflection_runs(symbol)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS improvement_records (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            reflection_run_id UUID REFERENCES reflection_runs(id) ON DELETE SET NULL,
            category VARCHAR(30) NOT NULL
                CHECK (category IN ('parameter_tuning', 'agent_config', 'risk_calibration', 'data_quality')),
            description TEXT NOT NULL,
            severity VARCHAR(10) NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
            metric_before DOUBLE PRECISION,
            metric_after DOUBLE PRECISION,
            rationale TEXT NOT NULL DEFAULT '',
            suggested_params JSONB NOT NULL DEFAULT '{}'::jsonb,
            applied BOOLEAN NOT NULL DEFAULT false,
            applied_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_improvement_records_run_unique
            ON improvement_records(reflection_run_id, category, description)
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_improvement_records_created_at ON improvement_records(created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_improvement_records_category ON improvement_records(category)")
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_improvement_records_unapplied "
        "ON improvement_records(applied) WHERE applied = false"
    )


def downgrade() -> None:
    """Drop the improvement history tables."""
    op.execute("DROP TABLE IF EXISTS improvement_records CASCADE")
    op.execute("DROP TABLE IF EXISTS reflection_runs CASCADE")
