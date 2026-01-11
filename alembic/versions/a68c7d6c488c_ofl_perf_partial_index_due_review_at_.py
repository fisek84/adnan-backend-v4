"""ofl perf: partial index for due evaluation (review_at where delta is null)

Revision ID: a68c7d6c488c
Revises: fd424231669c
Create Date: 2026-01-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a68c7d6c488c"
down_revision: Union[str, None] = "fd424231669c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "ix_ofl_due_review_at_delta_null"
TABLE_NAME = "outcome_feedback_loop"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        TABLE_NAME,
        ["review_at"],
        unique=False,
        postgresql_where=sa.text("delta IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        INDEX_NAME,
        table_name=TABLE_NAME,
    )
