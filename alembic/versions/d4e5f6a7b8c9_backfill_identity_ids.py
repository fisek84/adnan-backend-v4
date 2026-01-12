"""
backfill identity_id for existing records

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-01-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
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


def upgrade() -> None:
    conn = op.get_bind()

    # create identities (only if identity_root exists)
    if _has_table(conn, "identity_root"):
        # Idempotent insert WITHOUT assuming a UNIQUE constraint exists
        op.execute(
            """
            INSERT INTO identity_root (identity_type)
            SELECT v.identity_type
            FROM (VALUES ('system'), ('CEO'), ('agent')) AS v(identity_type)
            WHERE NOT EXISTS (
                SELECT 1 FROM identity_root i WHERE i.identity_type = v.identity_type
            );
            """
        )

    # decision_outcome_registry backfill (only if identity_id column exists on this branch)
    if (
        _has_table(conn, "decision_outcome_registry")
        and _has_column(conn, "decision_outcome_registry", "identity_id")
        and _has_table(conn, "identity_root")
    ):
        op.execute(
            """
            UPDATE decision_outcome_registry d
            SET identity_id = i.identity_id
            FROM identity_root i
            WHERE
                d.identity_id IS NULL
                AND i.identity_type =
                    CASE
                        WHEN d.owner IS NULL OR btrim(d.owner) = '' THEN 'system'
                        WHEN lower(btrim(d.owner)) = 'ceo' THEN 'CEO'
                        WHEN lower(btrim(d.owner)) = 'agent' THEN 'agent'
                        WHEN lower(btrim(d.owner)) = 'system' THEN 'system'
                        ELSE 'system'
                    END;
            """
        )

        # catch-all: anything still NULL -> system
        op.execute(
            """
            UPDATE decision_outcome_registry d
            SET identity_id = i.identity_id
            FROM identity_root i
            WHERE
                d.identity_id IS NULL
                AND i.identity_type = 'system';
            """
        )

    # outcome_feedback_loop backfill (only if identity_id column exists)
    if (
        _has_table(conn, "outcome_feedback_loop")
        and _has_column(conn, "outcome_feedback_loop", "identity_id")
        and _has_table(conn, "identity_root")
    ):
        op.execute(
            """
            UPDATE outcome_feedback_loop o
            SET identity_id = i.identity_id
            FROM identity_root i
            WHERE
                o.identity_id IS NULL
                AND i.identity_type =
                    CASE
                        WHEN o.owner IS NULL OR btrim(o.owner) = '' THEN 'system'
                        WHEN lower(btrim(o.owner)) = 'ceo' THEN 'CEO'
                        WHEN lower(btrim(o.owner)) = 'agent' THEN 'agent'
                        WHEN lower(btrim(o.owner)) = 'system' THEN 'system'
                        ELSE 'system'
                    END;
            """
        )

        # catch-all: anything still NULL -> system
        op.execute(
            """
            UPDATE outcome_feedback_loop o
            SET identity_id = i.identity_id
            FROM identity_root i
            WHERE
                o.identity_id IS NULL
                AND i.identity_type = 'system';
            """
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_table(conn, "decision_outcome_registry") and _has_column(
        conn, "decision_outcome_registry", "identity_id"
    ):
        op.execute("UPDATE decision_outcome_registry SET identity_id = NULL;")

    if _has_table(conn, "outcome_feedback_loop") and _has_column(
        conn, "outcome_feedback_loop", "identity_id"
    ):
        op.execute("UPDATE outcome_feedback_loop SET identity_id = NULL;")
