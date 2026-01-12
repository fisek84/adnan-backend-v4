"""
add identity_id foreign keys

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-01-12
"""

from alembic import op
from sqlalchemy import inspect

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def _has_table(conn, table_name: str) -> bool:
    insp = inspect(conn)
    return table_name in insp.get_table_names()


def _has_column(conn, table_name: str, column_name: str) -> bool:
    insp = inspect(conn)
    try:
        cols = insp.get_columns(table_name)
    except Exception:
        return False
    return any(c.get("name") == column_name for c in cols)


def _fk_exists(conn, table_name: str, fk_name: str) -> bool:
    insp = inspect(conn)
    try:
        fks = insp.get_foreign_keys(table_name)
    except Exception:
        return False
    return any(fk.get("name") == fk_name for fk in fks)


def upgrade() -> None:
    conn = op.get_bind()

    # DOR FK (only if table+column exist on this branch)
    if (
        _has_table(conn, "decision_outcome_registry")
        and _has_column(conn, "decision_outcome_registry", "identity_id")
        and _has_table(conn, "identity_root")
        and not _fk_exists(conn, "decision_outcome_registry", "fk_dor_identity")
    ):
        op.create_foreign_key(
            "fk_dor_identity",
            "decision_outcome_registry",
            "identity_root",
            ["identity_id"],
            ["identity_id"],
            ondelete="RESTRICT",
        )

    # OFL FK (only if table+column exist)
    if (
        _has_table(conn, "outcome_feedback_loop")
        and _has_column(conn, "outcome_feedback_loop", "identity_id")
        and _has_table(conn, "identity_root")
        and not _fk_exists(conn, "outcome_feedback_loop", "fk_ofl_identity")
    ):
        op.create_foreign_key(
            "fk_ofl_identity",
            "outcome_feedback_loop",
            "identity_root",
            ["identity_id"],
            ["identity_id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Drop only if it exists (branch-safe)
    if _has_table(conn, "outcome_feedback_loop") and _fk_exists(
        conn, "outcome_feedback_loop", "fk_ofl_identity"
    ):
        op.drop_constraint(
            "fk_ofl_identity", "outcome_feedback_loop", type_="foreignkey"
        )

    if _has_table(conn, "decision_outcome_registry") and _fk_exists(
        conn, "decision_outcome_registry", "fk_dor_identity"
    ):
        op.drop_constraint(
            "fk_dor_identity", "decision_outcome_registry", type_="foreignkey"
        )
