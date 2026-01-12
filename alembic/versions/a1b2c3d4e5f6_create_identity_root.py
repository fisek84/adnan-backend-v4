"""
create_identity_root

Revision ID: a1b2c3d4e5f6
Revises: 0ce16c3ca2c2
Create Date: 2026-01-12
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "a1b2c3d4e5f6"
down_revision = "0ce16c3ca2c2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # enable pgcrypto for gen_random_uuid (SAFE / idempotent)
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    op.create_table(
        "identity_root",
        sa.Column(
            "identity_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "identity_type",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )


def downgrade() -> None:
    op.drop_table("identity_root")
