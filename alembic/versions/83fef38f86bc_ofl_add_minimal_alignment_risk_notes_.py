"""ofl_add_minimal_alignment_risk_notes_columns

Revision ID: 83fef38f86bc
Revises: a68c7d6c488c
Create Date: 2026-01-10 21:55:22.031971

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "83fef38f86bc"
down_revision: Union[str, None] = "a68c7d6c488c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "outcome_feedback_loop"


def upgrade() -> None:
    op.add_column(TABLE_NAME, sa.Column("alignment_before", sa.dialects.postgresql.JSONB(), nullable=True))
    op.add_column(TABLE_NAME, sa.Column("alignment_after", sa.dialects.postgresql.JSONB(), nullable=True))
    op.add_column(TABLE_NAME, sa.Column("delta_score", sa.Numeric(18, 6), nullable=True))
    op.add_column(TABLE_NAME, sa.Column("delta_risk", sa.Numeric(18, 6), nullable=True))
    op.add_column(TABLE_NAME, sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column(TABLE_NAME, "notes")
    op.drop_column(TABLE_NAME, "delta_risk")
    op.drop_column(TABLE_NAME, "delta_score")
    op.drop_column(TABLE_NAME, "alignment_after")
    op.drop_column(TABLE_NAME, "alignment_before")
