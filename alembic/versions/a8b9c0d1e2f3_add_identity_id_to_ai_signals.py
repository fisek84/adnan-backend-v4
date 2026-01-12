# alembic/versions/a8b9c0d1e2f3_add_identity_id_to_ai_signals.py
"""
add identity_id to ai_signals

Revision ID: a8b9c0d1e2f3
Revises: a1b2c3d4e5f6
Create Date: 2026-01-12
"""

from alembic import op
import sqlalchemy as sa

revision = "a8b9c0d1e2f3"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_signals", sa.Column("identity_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_signals", "identity_id")
