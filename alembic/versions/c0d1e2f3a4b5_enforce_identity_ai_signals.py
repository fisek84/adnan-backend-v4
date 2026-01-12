"""
enforce identity_id on ai_signals + FK to identity_root

Revision ID: c0d1e2f3a4b5
Revises: b4fd3961bad5
Create Date: 2026-01-12
"""

from alembic import op
import sqlalchemy as sa  # noqa: F401

revision = "c0d1e2f3a4b5"
down_revision = "b4fd3961bad5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # identity_root.identity_id je UUID (iz errora), zato ai_signals.identity_id mora biti UUID prije FK
    # b4fd3961bad5 već konvertuje ai_signals.identity_id -> UUID; ovdje samo enforce + FK.

    # fail-fast: ne dozvoli NULL prije NOT NULL
    op.execute(
        """
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM ai_signals WHERE identity_id IS NULL) THEN
            RAISE EXCEPTION 'ai_signals.identity_id contains NULL; cannot enforce NOT NULL';
          END IF;
        END $$;
        """
    )

    # NOT NULL
    op.execute("ALTER TABLE ai_signals ALTER COLUMN identity_id SET NOT NULL;")

    # FK (types must match: uuid -> uuid)
    op.create_foreign_key(
        "fk_ai_signals_identity",
        "ai_signals",
        "identity_root",
        ["identity_id"],
        ["identity_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint("fk_ai_signals_identity", "ai_signals", type_="foreignkey")
    op.execute("ALTER TABLE ai_signals ALTER COLUMN identity_id DROP NOT NULL;")
