from __future__ import annotations

import os
from typing import Any, Dict, Optional

from sqlalchemy import create_engine, text

_DATABASE_URL = os.getenv("DATABASE_URL")
if not _DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

_engine = create_engine(_DATABASE_URL, pool_pre_ping=True)


def insert_decision_history(
    *,
    decision_id: str,
    identity_id,
    origin: Optional[str],
    executor: Optional[str],
    command: Optional[str],
    payload: Optional[Dict[str, Any]],
    confidence: Optional[float],
    confirmed: bool,
) -> None:
    with _engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO decision_history (
                    decision_id,
                    identity_id,
                    origin,
                    executor,
                    command,
                    payload,
                    confidence,
                    confirmed
                )
                VALUES (
                    :decision_id,
                    :identity_id,
                    :origin,
                    :executor,
                    :command,
                    :payload,
                    :confidence,
                    :confirmed
                )
                """
            ),
            {
                "decision_id": decision_id,
                "identity_id": identity_id,
                "origin": origin,
                "executor": executor,
                "command": command,
                "payload": payload,
                "confidence": confidence,
                "confirmed": confirmed,
            },
        )
