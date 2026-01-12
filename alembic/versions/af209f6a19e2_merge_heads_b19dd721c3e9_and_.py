"""merge heads b19dd721c3e9 and b4fd3961bad5

Revision ID: af209f6a19e2
Revises: b19dd721c3e9, b4fd3961bad5
Create Date: 2026-01-12 23:04:49.697756

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'af209f6a19e2'
down_revision: Union[str, None] = ('b19dd721c3e9', 'b4fd3961bad5')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
