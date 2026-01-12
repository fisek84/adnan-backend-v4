from __future__ import annotations

import os

from sqlalchemy import create_engine, text

_DATABASE_URL = os.getenv("DATABASE_URL")
if not _DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

_engine = create_engine(_DATABASE_URL, pool_pre_ping=True)


def resolve_identity_id(identity_type: str) -> str:
    with _engine.begin() as conn:
        row = conn.execute(
            text(
                """
                SELECT identity_id
                FROM identity_root
                WHERE identity_type = :t
                LIMIT 1
                """
            ),
            {"t": identity_type},
        ).fetchone()

        if not row:
            raise RuntimeError(f"identity_type not found: {identity_type}")

        return str(row[0])
