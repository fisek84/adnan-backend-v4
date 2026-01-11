from __future__ import annotations

import logging
import os
from typing import Any, Dict, List, Optional

import sqlalchemy as sa

from services.decision_outcome_registry import get_decision_outcome_registry
from services.identity_loader import load_ceo_identity_pack
from services.ceo_alignment_engine import CEOAlignmentEngine
from services.world_state_engine import WorldStateEngine

logger = logging.getLogger(__name__)


def _db_engine() -> sa.Engine:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        raise RuntimeError("DATABASE_URL is not set")
    return sa.create_engine(db_url, pool_pre_ping=True, future=True)


class AlignmentDriftMonitor:
    """
    Periodični monitor koji detektuje tihi alignment drift
    između identity immutable laws i stvarnih odluka.
    """

    SIGNAL_TYPE = "alignment_drift"
    SOURCE = "alignment_drift_monitor"

    def run(self, limit: int = 50) -> Dict[str, Any]:
        dor = get_decision_outcome_registry()
        decisions = dor.list_recent(limit)

        if not decisions:
            return {"ok": True, "processed": 0, "signals": 0}

        identity = load_ceo_identity_pack()
        immutable_laws = (
            identity.get("immutable_laws")
            or identity.get("kernel", {}).get("immutable_laws")
        )

        if not isinstance(immutable_laws, list):
            return {"ok": False, "error": "immutable_laws_missing"}

        engine = _db_engine()
        inserted = 0

        world = WorldStateEngine().build_snapshot()
        alignment = CEOAlignmentEngine().evaluate(identity, world)

        violated_law, severity = self._detect_violation(alignment)

        if not violated_law:
            return {"ok": True, "processed": len(decisions), "signals": 0}

        with engine.begin() as conn:
            for d in decisions:
                conn.execute(
                    sa.text(
                        """
                        INSERT INTO ai_signals
                        (signal_type, source, subject_id, drift_detected, law_violated, severity)
                        VALUES
                        (:signal_type, :source, :subject_id, true, :law_violated, :severity)
                        """
                    ),
                    {
                        "signal_type": self.SIGNAL_TYPE,
                        "source": self.SOURCE,
                        "subject_id": d.get("decision_id"),
                        "law_violated": violated_law,
                        "severity": severity,
                    },
                )
                inserted += 1

        return {
            "ok": True,
            "processed": len(decisions),
            "signals": inserted,
        }

    def _detect_violation(
        self, alignment_snapshot: Dict[str, Any]
    ) -> tuple[Optional[str], Optional[str]]:
        law = alignment_snapshot.get("law_compliance")
        if not isinstance(law, dict):
            return None, None

        risk = (law.get("risk_level") or "").lower()
        violated = law.get("violated_law")

        if risk in {"medium", "high"} and isinstance(violated, str):
            return violated, risk

        return None, None
