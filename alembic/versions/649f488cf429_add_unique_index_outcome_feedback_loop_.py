"""add unique index outcome_feedback_loop decision_id window_days

Revision ID: 649f488cf429
Revises: 2413dc5a0e58
Create Date: 2026-01-10 20:40:55.510090

"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa  # noqa: F401


# revision identifiers, used by Alembic.
revision: str = "649f488cf429"
down_revision: Union[str, None] = "2413dc5a0e58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "uq_outcome_feedback_loop_decision_id_window_days"
TABLE_NAME = "outcome_feedback_loop"


def upgrade() -> None:
    """
    Enforce idempotency for scheduling reviews:
      unique(decision_id, evaluation_window_days)

    This enables INSERT .. ON CONFLICT DO NOTHING in the service layer.
    """
    op.create_index(
        INDEX_NAME,
        TABLE_NAME,
        ["decision_id", "evaluation_window_days"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
