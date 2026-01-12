"""dor add approval_id execution_id unique indexes

Revision ID: 157956357fc4
Revises: cedfafa85bf5
Create Date: 2026-01-12

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "157956357fc4"
down_revision: Union[str, None] = "cedfafa85bf5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLE_NAME = "decision_outcome_registry"

UQ_APPROVAL = "uq_decision_outcome_registry_approval_id"
UQ_EXECUTION = "uq_decision_outcome_registry_execution_id"


def upgrade() -> None:
    op.add_column(
        TABLE_NAME,
        sa.Column("approval_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        TABLE_NAME,
        sa.Column("execution_id", sa.String(length=128), nullable=True),
    )

    op.add_column(
        TABLE_NAME,
        sa.Column("approval_status", sa.String(length=32), nullable=True),
    )
    op.add_column(
        TABLE_NAME,
        sa.Column("execution_state", sa.String(length=32), nullable=True),
    )
    op.add_column(
        TABLE_NAME,
        sa.Column("failure", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        TABLE_NAME,
        sa.Column("result_keys", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        TABLE_NAME,
        sa.Column("feedback", sa.Text(), nullable=True),
    )

    op.create_index(
        UQ_APPROVAL,
        TABLE_NAME,
        ["approval_id"],
        unique=True,
        postgresql_where=sa.text("approval_id IS NOT NULL"),
    )
    op.create_index(
        UQ_EXECUTION,
        TABLE_NAME,
        ["execution_id"],
        unique=True,
        postgresql_where=sa.text("execution_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(UQ_EXECUTION, table_name=TABLE_NAME)
    op.drop_index(UQ_APPROVAL, table_name=TABLE_NAME)

    op.drop_column(TABLE_NAME, "feedback")
    op.drop_column(TABLE_NAME, "result_keys")
    op.drop_column(TABLE_NAME, "failure")
    op.drop_column(TABLE_NAME, "execution_state")
    op.drop_column(TABLE_NAME, "approval_status")
    op.drop_column(TABLE_NAME, "execution_id")
    op.drop_column(TABLE_NAME, "approval_id")
