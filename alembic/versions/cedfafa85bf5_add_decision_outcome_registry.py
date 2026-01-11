"""add decision_outcome_registry

Revision ID: cedfafa85bf5
Revises: 83fef38f86bc
Create Date: 2026-01-11 13:05:58.966532

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "cedfafa85bf5"
down_revision: Union[str, None] = "83fef38f86bc"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "decision_outcome_registry",
        sa.Column(
            "decision_id", sa.String(length=128), primary_key=True, nullable=False
        ),
        sa.Column(
            "timestamp",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("alignment_snapshot_hash", sa.String(length=128), nullable=True),
        sa.Column("behaviour_mode", sa.String(length=64), nullable=True),
        sa.Column("recommendation_type", sa.String(length=64), nullable=True),
        sa.Column("recommendation_summary", sa.Text(), nullable=True),
        sa.Column(
            "accepted", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "executed", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "execution_result",
            sa.String(length=16),
            nullable=True,
        ),  # success|fail|partial
        sa.Column(
            "owner",
            sa.String(length=16),
            nullable=True,
        ),  # CEO|agent|system
    )

    op.create_index(
        "ix_decision_outcome_registry_timestamp",
        "decision_outcome_registry",
        ["timestamp"],
    )
    op.create_index(
        "ix_decision_outcome_registry_alignment_snapshot_hash",
        "decision_outcome_registry",
        ["alignment_snapshot_hash"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_decision_outcome_registry_alignment_snapshot_hash",
        table_name="decision_outcome_registry",
    )
    op.drop_index(
        "ix_decision_outcome_registry_timestamp",
        table_name="decision_outcome_registry",
    )
    op.drop_table("decision_outcome_registry")
