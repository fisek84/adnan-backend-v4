"""
ai_signals identity_id to uuid

Revision ID: b4fd3961bad5
Revises: b9c0d1e2f3a4
Create Date: 2026-01-12
"""

from alembic import op
import sqlalchemy as sa


revision = "b4fd3961bad5"
down_revision = "b9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    col_type = bind.execute(
        sa.text(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'ai_signals'
              AND column_name = 'identity_id'
            """
        )
    ).scalar()

    # Ako je već uuid, ova migracija je efektivno odrađena (ili dio nje), ne diraj dalje.
    if col_type == "uuid":
        return

    # 1) Normalizuj prazne/whitespace stringove -> NULL (cast u text radi sigurnosti)
    op.execute(
        """
        UPDATE ai_signals
        SET identity_id = NULL
        WHERE identity_id IS NOT NULL
          AND btrim(identity_id::text) = '';
        """
    )

    # 2) Nulluj sve što nije UUID format (da cast ne pukne)
    op.execute(
        """
        UPDATE ai_signals
        SET identity_id = NULL
        WHERE identity_id IS NOT NULL
          AND btrim(identity_id::text) !~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$';
        """
    )

    # 3) Konverzija tipa VARCHAR/TEXT -> UUID
    op.execute("ALTER TABLE ai_signals ALTER COLUMN identity_id DROP DEFAULT;")
    op.execute(
        """
        ALTER TABLE ai_signals
        ALTER COLUMN identity_id TYPE uuid
        USING identity_id::uuid;
        """
    )


def downgrade() -> None:
    # Best-effort: uuid -> text; ako je već text/varchar, neće dirati.
    bind = op.get_bind()
    col_type = bind.execute(
        sa.text(
            """
            SELECT data_type
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = 'ai_signals'
              AND column_name = 'identity_id'
            """
        )
    ).scalar()

    if col_type != "uuid":
        return

    op.execute(
        """
        ALTER TABLE ai_signals
        ALTER COLUMN identity_id TYPE varchar
        USING identity_id::text;
        """
    )
