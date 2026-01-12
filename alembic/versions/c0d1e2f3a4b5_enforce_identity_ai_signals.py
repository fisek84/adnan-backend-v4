"""
enforce identity_id for ai_signals

Revision ID: c0d1e2f3a4b5
Revises: b9c0d1e2f3a4
Create Date: 2026-01-12
"""

from alembic import op

revision = "c0d1e2f3a4b5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "ai_signals",
        "identity_id",
        nullable=False,
    )

    op.create_foreign_key(
        "fk_ai_signals_identity",
        "ai_signals",
        "identity_root",
        ["identity_id"],
        ["identity_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_ai_signals_identity",
        "ai_signals",
        type_="foreignkey",
    )
    op.alter_column(
        "ai_signals",
        "identity_id",
        nullable=True,
    )
