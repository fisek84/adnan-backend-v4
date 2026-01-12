"""
enforce identity_id NOT NULL

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-01-12
"""

from alembic import op
import sqlalchemy as sa

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def _has_column(conn, table_name: str, column_name: str) -> bool:
    q = sa.text(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = :t
          AND column_name = :c
        LIMIT 1
        """
    )
    return conn.execute(q, {"t": table_name, "c": column_name}).first() is not None


def upgrade() -> None:
    conn = op.get_bind()

    # decision_outcome_registry.identity_id may not exist on this migration path (multi-head).
    if _has_column(conn, "decision_outcome_registry", "identity_id"):
        op.alter_column(
            "decision_outcome_registry",
            "identity_id",
            nullable=False,
        )

    # outcome_feedback_loop.identity_id must exist (added in c3d4e5f6a7b8) on this branch.
    if _has_column(conn, "outcome_feedback_loop", "identity_id"):
        op.alter_column(
            "outcome_feedback_loop",
            "identity_id",
            nullable=False,
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_column(conn, "decision_outcome_registry", "identity_id"):
        op.alter_column(
            "decision_outcome_registry",
            "identity_id",
            nullable=True,
        )

    if _has_column(conn, "outcome_feedback_loop", "identity_id"):
        op.alter_column(
            "outcome_feedback_loop",
            "identity_id",
            nullable=True,
        )
