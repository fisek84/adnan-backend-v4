"""ofl hardening: NOT NULL review_at + evaluation_window_days (fail-fast)

Revision ID: fd424231669c
Revises: 649f488cf429
Create Date: 2026-01-10

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "fd424231669c"
down_revision: Union[str, None] = "649f488cf429"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "outcome_feedback_loop"


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            DO $$
            BEGIN
              IF EXISTS (SELECT 1 FROM {TABLE_NAME} WHERE review_at IS NULL) THEN
                RAISE EXCEPTION 'cannot_set_not_null:{TABLE_NAME}.review_at has NULL rows';
              END IF;

              IF EXISTS (SELECT 1 FROM {TABLE_NAME} WHERE evaluation_window_days IS NULL) THEN
                RAISE EXCEPTION 'cannot_set_not_null:{TABLE_NAME}.evaluation_window_days has NULL rows';
              END IF;
            END $$;
            """
        )
    )

    op.alter_column(
        TABLE_NAME,
        "review_at",
        existing_type=sa.DateTime(),
        nullable=False,
    )
    op.alter_column(
        TABLE_NAME,
        "evaluation_window_days",
        existing_type=sa.Integer(),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        TABLE_NAME,
        "review_at",
        existing_type=sa.DateTime(),
        nullable=True,
    )
    op.alter_column(
        TABLE_NAME,
        "evaluation_window_days",
        existing_type=sa.Integer(),
        nullable=True,
    )
