"""create memory plane tables

Revision ID: 5b1d7e4c2a90
Revises: 3f2a1c9b7d10
Create Date: 2026-03-17

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "5b1d7e4c2a90"
down_revision: str | None = "3f2a1c9b7d10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "memory_item",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1), primary_key=True),
        sa.Column(
            "stored_id",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "idempotency_key",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column(
            "schema_version",
            sa.String(length=64),
            nullable=False,
            server_default=sa.text("'memory_write.v1'"),
        ),
        sa.Column("item_type", sa.String(length=64), nullable=False),
        sa.Column("item_text", sa.Text(), nullable=False),
        sa.Column("item_tags", postgresql.JSONB(), nullable=False),
        sa.Column("item_source", sa.String(length=64), nullable=False),
        sa.Column("grounded_on", postgresql.JSONB(), nullable=False),
        sa.Column("approval_id", sa.String(length=128), nullable=False),
        sa.Column("execution_id", sa.String(length=128), nullable=True),
        sa.Column("identity_id", sa.String(length=128), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("idempotency_key", name="uq_memory_item_idempotency_key"),
        sa.UniqueConstraint("stored_id", name="uq_memory_item_stored_id"),
    )

    op.create_index(
        "ix_memory_item_created_at",
        "memory_item",
        ["created_at"],
    )
    op.create_index(
        "ix_memory_item_identity_id",
        "memory_item",
        ["identity_id"],
    )

    op.create_table(
        "memory_write_audit_event",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("op", sa.String(length=128), nullable=False),
        sa.Column("approval_id", sa.String(length=128), nullable=True),
        sa.Column("execution_id", sa.String(length=128), nullable=True),
        sa.Column("identity_id", sa.String(length=128), nullable=True),
        sa.Column("stored_id", sa.String(length=128), nullable=True),
        sa.Column(
            "ok",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("source", sa.String(length=64), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
    )

    op.create_index(
        "ix_memory_write_audit_event_created_at",
        "memory_write_audit_event",
        ["created_at"],
    )
    op.create_index(
        "ix_memory_write_audit_event_approval_id",
        "memory_write_audit_event",
        ["approval_id"],
    )

    op.create_table(
        "memory_scope_kv",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1), primary_key=True),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("scope_id", sa.String(length=128), nullable=False),
        sa.Column("key", sa.String(length=256), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column(
            "ts_unix",
            sa.Float(),
            nullable=False,
        ),
        sa.Column(
            "exp_unix",
            sa.Float(),
            nullable=True,
        ),
        sa.Column("meta", postgresql.JSONB(), nullable=False),
        sa.UniqueConstraint(
            "scope_type",
            "scope_id",
            "key",
            name="uq_memory_scope_kv_scope_key",
        ),
    )

    op.create_index(
        "ix_memory_scope_kv_scope",
        "memory_scope_kv",
        ["scope_type", "scope_id"],
    )
    op.create_index(
        "ix_memory_scope_kv_exp_unix",
        "memory_scope_kv",
        ["exp_unix"],
    )

    op.create_table(
        "conversation_turn",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1), primary_key=True),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column(
            "t_unix",
            sa.Float(),
            nullable=False,
        ),
        sa.Column("user_text", sa.Text(), nullable=False),
        sa.Column("assistant_text", sa.Text(), nullable=False),
    )

    op.create_index(
        "ix_conversation_turn_conversation_id_t_unix",
        "conversation_turn",
        ["conversation_id", "t_unix"],
    )

    op.create_table(
        "conversation_meta_kv",
        sa.Column("id", sa.BigInteger(), sa.Identity(start=1), primary_key=True),
        sa.Column("conversation_id", sa.String(length=128), nullable=False),
        sa.Column("key", sa.String(length=256), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "conversation_id",
            "key",
            name="uq_conversation_meta_kv_conversation_key",
        ),
    )

    op.create_index(
        "ix_conversation_meta_kv_conversation_id",
        "conversation_meta_kv",
        ["conversation_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_conversation_meta_kv_conversation_id",
        table_name="conversation_meta_kv",
    )
    op.drop_table("conversation_meta_kv")

    op.drop_index(
        "ix_conversation_turn_conversation_id_t_unix",
        table_name="conversation_turn",
    )
    op.drop_table("conversation_turn")

    op.drop_index("ix_memory_scope_kv_exp_unix", table_name="memory_scope_kv")
    op.drop_index("ix_memory_scope_kv_scope", table_name="memory_scope_kv")
    op.drop_table("memory_scope_kv")

    op.drop_index(
        "ix_memory_write_audit_event_approval_id",
        table_name="memory_write_audit_event",
    )
    op.drop_index(
        "ix_memory_write_audit_event_created_at",
        table_name="memory_write_audit_event",
    )
    op.drop_table("memory_write_audit_event")

    op.drop_index("ix_memory_item_identity_id", table_name="memory_item")
    op.drop_index("ix_memory_item_created_at", table_name="memory_item")
    op.drop_table("memory_item")
