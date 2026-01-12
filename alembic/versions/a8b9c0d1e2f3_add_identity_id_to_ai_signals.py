"""
add identity_id to ai_signals

Revision ID: a8b9c0d1e2f3
Revises: a767a3914519
Create Date: 2026-01-12
"""

from alembic import op
from sqlalchemy.dialects import postgresql
import sqlalchemy as sa

revision = "a8b9c0d1e2f3"
down_revision = "a767a3914519"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_signals",
        sa.Column(
            "identity_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("ai_signals", "identity_id")
