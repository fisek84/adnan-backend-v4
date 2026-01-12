"""
backfill identity_id for ai_signals

Revision ID: b9c0d1e2f3a4
Revises: a8b9c0d1e2f3
Create Date: 2026-01-12
"""

from alembic import op

revision = "b9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        UPDATE ai_signals s
        SET identity_id = i.identity_id
        FROM identity_root i
        WHERE
            s.identity_id IS NULL
            AND i.identity_type = CASE
                WHEN s.source = 'CEO' THEN 'CEO'
                WHEN s.source = 'agent' THEN 'agent'
                ELSE 'system'
            END;
    """)


def downgrade() -> None:
    op.execute("UPDATE ai_signals SET identity_id = NULL;")
