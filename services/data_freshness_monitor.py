from __future__ import annotations

import os
from typing import Any, Dict

import sqlalchemy as sa

from services.world_state_engine import WorldStateEngine


def _db_engine() -> sa.Engine:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set")
    return sa.create_engine(db_url, pool_pre_ping=True, future=True)


class DataFreshnessMonitor:
    """
    Kanonski Data Freshness Signal.
    Baziran na WorldStateEngine staleness indikacijama.
    """

    SIGNAL_TYPE = "data_freshness"
    SOURCE = "data_freshness_monitor"

    def run(self) -> Dict[str, Any]:
        snapshot = WorldStateEngine().build_snapshot()

        generated_at = snapshot.get("generated_at")
        if not generated_at:
            return {"ok": False, "error": "snapshot_missing_generated_at"}

        goals = snapshot.get("goals", {})
        tasks = snapshot.get("tasks", {})

        stale_goals = len(goals.get("stale", [])) if isinstance(goals, dict) else 0
        overdue_tasks = len(tasks.get("overdue", [])) if isinstance(tasks, dict) else 0
        data_quality_issues = len(tasks.get("data_quality", [])) if isinstance(tasks, dict) else 0

        # Deterministički score (jednostavan, čitljiv, bez magije)
        staleness_score = float(
            stale_goals * 1.0
            + overdue_tasks * 1.5
            + data_quality_issues * 0.5
        )

        engine = _db_engine()
        with engine.begin() as conn:
            conn.execute(
                sa.text(
                    """
                    INSERT INTO ai_signals
                    (signal_type, source, last_updated_at, staleness_score)
                    VALUES
                    (:signal_type, :source, :last_updated_at, :staleness_score)
                    """
                ),
                {
                    "signal_type": self.SIGNAL_TYPE,
                    "source": self.SOURCE,
                    "last_updated_at": generated_at,
                    "staleness_score": staleness_score,
                },
            )

        return {
            "ok": True,
            "last_updated_at": generated_at,
            "staleness_score": staleness_score,
            "components": {
                "stale_goals": stale_goals,
                "overdue_tasks": overdue_tasks,
                "data_quality_issues": data_quality_issues,
            },
        }
