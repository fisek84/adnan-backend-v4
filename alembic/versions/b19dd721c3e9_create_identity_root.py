"""create_identity_root

Revision ID: b19dd721c3e9
Revises: 01a578baf111
Create Date: 2026-01-12 22:44:43.638541

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b19dd721c3e9'
down_revision: Union[str, None] = '01a578baf111'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
