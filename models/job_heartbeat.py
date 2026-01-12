from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# Minimal SSOT table definition (used for migrations/tests; runtime can still autoload).
metadata = sa.MetaData()

job_heartbeat = sa.Table(
    "job_heartbeat",
    metadata,
    sa.Column("id", sa.BigInteger, primary_key=True),
    sa.Column("job_name", sa.Text, nullable=False),
    sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=False),
    sa.Column("status", sa.Text, nullable=False, server_default=sa.text("'ok'")),
    sa.Column("details", sa.Text, nullable=True),
    sa.Column("identity_id", UUID(as_uuid=True), nullable=True),
    sa.UniqueConstraint("job_name", name="uq_job_heartbeat_job_name"),
)
