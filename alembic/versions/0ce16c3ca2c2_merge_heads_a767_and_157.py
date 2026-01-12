"""merge heads a767 and 157

Revision ID: 0ce16c3ca2c2
Revises: a767a3914519, 157956357fc4
Create Date: 2026-01-12 13:17:49.291430

"""

from __future__ import annotations

from typing import Sequence, Union


# revision identifiers, used by Alembic.
revision: str = "0ce16c3ca2c2"
down_revision: Union[str, None] = ("a767a3914519", "157956357fc4")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
