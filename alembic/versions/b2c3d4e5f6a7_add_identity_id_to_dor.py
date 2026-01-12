"""
add identity_id to decision_outcome_registry

Revision ID: b2c3d4e5f6a7
Revises: 157956357fc4
Create Date: 2026-01-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "b2c3d4e5f6a7"
down_revision = "157956357fc4"
branch_labels = None
depends_on = None

TABLE_NAME = "decision_outcome_registry"


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
