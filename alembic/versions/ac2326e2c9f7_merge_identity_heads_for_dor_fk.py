"""merge identity heads for dor fk

Revision ID: ac2326e2c9f7
Revises: b2c3d4e5f6a7, c0d1e2f3a4b5, d1e2f3a4b5c6
Create Date: 2026-01-12 17:29:25.415850
"""

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "ac2326e2c9f7"
down_revision: Union[str, Sequence[str], None] = (
    "b2c3d4e5f6a7",
    "c0d1e2f3a4b5",
    "d1e2f3a4b5c6",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
