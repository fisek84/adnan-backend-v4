"""add ai_signals table

Revision ID: a767a3914519
Revises: cedfafa85bf5
Create Date: 2026-01-11 20:19:59.499858

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "a767a3914519"
down_revision: Union[str, None] = "cedfafa85bf5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "ai_signals",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1), primary_key=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("signal_type", sa.String(length=64), nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("subject_id", sa.String(length=256), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("drift_detected", sa.Boolean(), nullable=True),
        sa.Column("law_violated", sa.String(length=256), nullable=True),
        sa.Column("severity", sa.String(length=16), nullable=True),
        sa.Column("last_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("staleness_score", sa.Float(), nullable=True),
    )

    op.create_index(
        "ix_ai_signals_generated_at",
        "ai_signals",
        ["generated_at"],
    )
    op.create_index(
        "ix_ai_signals_signal_type_generated_at",
        "ai_signals",
        ["signal_type", "generated_at"],
    )
    op.create_index(
        "ix_ai_signals_subject_id",
        "ai_signals",
        ["subject_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_signals_subject_id", table_name="ai_signals")
    op.drop_index("ix_ai_signals_signal_type_generated_at", table_name="ai_signals")
    op.drop_index("ix_ai_signals_generated_at", table_name="ai_signals")
    op.drop_table("ai_signals")
