"""
add missing fk_dor_identity (post-merge)

Revision ID: 01a578baf111
Revises: ac2326e2c9f7
Create Date: 2026-01-12
"""

from alembic import op
from sqlalchemy import inspect

# revision identifiers, used by Alembic.
revision = "01a578baf111"
down_revision = "ac2326e2c9f7"
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

    # Only add FK if:
    # - decision_outcome_registry exists
    # - identity_id column exists on DOR
    # - identity_root exists
    # - FK not already present (idempotent)
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


def downgrade() -> None:
    conn = op.get_bind()

    if _has_table(conn, "decision_outcome_registry") and _fk_exists(
        conn, "decision_outcome_registry", "fk_dor_identity"
    ):
        op.drop_constraint(
            "fk_dor_identity",
            "decision_outcome_registry",
            type_="foreignkey",
        )
