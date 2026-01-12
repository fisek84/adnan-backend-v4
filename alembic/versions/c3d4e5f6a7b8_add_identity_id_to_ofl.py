"""
add identity_id to outcome_feedback_loop

Revision ID: c3d4e5f6a7b8
Revises: fd424231669c
Create Date: 2026-01-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "c3d4e5f6a7b8"
down_revision = "fd424231669c"
branch_labels = None
depends_on = None

TABLE_NAME = "outcome_feedback_loop"


def upgrade() -> None:
    op.add_column(
        TABLE_NAME,
        sa.Column(
            "identity_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(TABLE_NAME, "identity_id")
