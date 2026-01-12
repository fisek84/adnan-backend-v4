import os
from typing import Any, Optional, Dict

import sqlalchemy as sa


def _db_url() -> str:
    return (os.getenv("DATABASE_URL") or "").strip()


def insert_decision_history(
    *,
    decision_id: str,
    identity_id: str,
    origin: str,
    executor: Optional[str],
    command: str,
    payload: Dict[str, Any],
    confidence: Optional[float],
    confirmed: bool,
) -> None:
    db_url = _db_url()
    if not db_url:
        # BEST-EFFORT: no DB configured => skip, do not crash runtime
        return

    engine = sa.create_engine(db_url, pool_pre_ping=True, future=True)

    with engine.begin() as conn:
        conn.execute(
            sa.text(
                """
                INSERT INTO decision_history
                  (decision_id, identity_id, origin, executor, command, payload, confidence, confirmed)
                VALUES
                  (:decision_id, :identity_id, :origin, :executor, :command, CAST(:payload AS jsonb), :confidence, :confirmed)
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
                "confirmed": bool(confirmed),
            },
        )
