"""
create_outcome_feedback_loop

Revision ID: 2413dc5a0e58
Revises:
Create Date: 2026-01-10
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "2413dc5a0e58"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "outcome_feedback_loop",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1), primary_key=True),
        sa.Column("decision_id", sa.Text(), nullable=False),
        # kada je zapis kreiran (u bazi)
        sa.Column(
            "timestamp",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        # kada treba raditi review (npr. +7/+14/+30 dana)
        sa.Column("review_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("evaluation_window_days", sa.Integer(), nullable=True),
        # alignment/mode info
        sa.Column("alignment_snapshot_hash", sa.Text(), nullable=True),
        sa.Column("behaviour_mode", sa.Text(), nullable=True),
        # recommendation info
        sa.Column("recommendation_type", sa.Text(), nullable=True),
        sa.Column("recommendation_summary", sa.Text(), nullable=False),
        # outcome flags
        sa.Column(
            "accepted", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "executed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("execution_result", sa.Text(), nullable=True),  # success/fail/partial
        sa.Column("owner", sa.Text(), nullable=True),  # CEO/agent/system
        # opcionalno: KPI snapshots / delta (JSONB)
        sa.Column("kpi_before", postgresql.JSONB(), nullable=True),
        sa.Column("kpi_after", postgresql.JSONB(), nullable=True),
        sa.Column("delta", postgresql.JSONB(), nullable=True),
    )

    op.create_index(
        "ix_outcome_feedback_loop_decision_id",
        "outcome_feedback_loop",
        ["decision_id"],
        schema="public",
    )
    op.create_index(
        "ix_outcome_feedback_loop_review_at",
        "outcome_feedback_loop",
        ["review_at"],
        schema="public",
    )


def downgrade() -> None:
    # SAFE downgrade: ne puca ako indeksi/tabela ne postoje (tvoj trenutni problem)
    op.execute("DROP INDEX IF EXISTS public.ix_outcome_feedback_loop_review_at")
    op.execute("DROP INDEX IF EXISTS public.ix_outcome_feedback_loop_decision_id")
    op.execute("DROP TABLE IF EXISTS public.outcome_feedback_loop")
