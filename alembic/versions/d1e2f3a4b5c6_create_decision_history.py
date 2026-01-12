"""
create decision_history (append-only)

Revision ID: d1e2f3a4b5c6
Revises: f6a7b8c9d0e1
Create Date: 2026-01-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "d1e2f3a4b5c6"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "decision_history",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1), primary_key=True),
        sa.Column("decision_id", sa.String(length=128), nullable=False),
        sa.Column(
            "identity_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("origin", sa.String(length=64), nullable=True),
        sa.Column("executor", sa.String(length=64), nullable=True),
        sa.Column("command", sa.String(length=128), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column(
            "confirmed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )

    op.create_index(
        "ix_decision_history_decision_id",
        "decision_history",
        ["decision_id"],
    )
    op.create_index(
        "ix_decision_history_created_at",
        "decision_history",
        ["created_at"],
    )

    op.create_foreign_key(
        "fk_decision_history_identity",
        "decision_history",
        "identity_root",
        ["identity_id"],
        ["identity_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_decision_history_identity",
        "decision_history",
        type_="foreignkey",
    )
    op.drop_index("ix_decision_history_created_at", table_name="decision_history")
    op.drop_index("ix_decision_history_decision_id", table_name="decision_history")
    op.drop_table("decision_history")
