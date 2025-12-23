# C:\adnan-backend-v4\services\sop_knowledge_intelligence.py

from typing import Dict, Any, List, Optional

from services.sop_knowledge_registry import SOPKnowledgeRegistry


class SOPKnowledgeIntelligence:
    """
    SOP Knowledge Intelligence (READ-ONLY)

    PURPOSE:
    - Reasoning over SOP definitions
    - No execution
    - No state changes
    - No side effects
    """

    def __init__(self):
        self._registry = SOPKnowledgeRegistry()

    # --------------------------------------------------
    # BASIC ACCESS
    # --------------------------------------------------
    def list_sops(self) -> List[Dict[str, Any]]:
        """
        Lightweight SOP list for reasoning / UI.
        """
        return self._registry.list_sops()

    def get_sop_summary(self, sop_id: str) -> Optional[Dict[str, Any]]:
        """
        Human-readable SOP understanding.
        """
        sop = self._registry.get_sop(sop_id, mode="summary")
        if not sop:
            return None

        steps = sop.get("steps", [])

        critical_steps = [s for s in steps if s.get("critical") is True]

        parallel_steps = [s for s in steps if s.get("parallel") is True]

        return {
            "sop_id": sop_id,
            "name": sop.get("name"),
            "description": sop.get("description"),
            "total_steps": len(steps),
            "critical_steps": len(critical_steps),
            "parallel_steps": len(parallel_steps),
        }

    # --------------------------------------------------
    # RISK & COMPLEXITY
    # --------------------------------------------------
    def assess_risk(self, sop_id: str) -> Optional[Dict[str, Any]]:
        sop = self._registry.get_sop(sop_id, mode="full")
        if not sop:
            return None

        steps = sop.get("steps", [])

        risk_score = 0
        reasons: List[str] = []

        for s in steps:
            if s.get("critical"):
                risk_score += 2
                reasons.append(f"Critical step: {s.get('step')}")

            if s.get("parallel"):
                risk_score += 1
                reasons.append(f"Parallel execution: {s.get('step')}")

        if risk_score >= 5:
            level = "high"
        elif risk_score >= 3:
            level = "medium"
        else:
            level = "low"

        return {
            "sop_id": sop_id,
            "risk_level": level,
            "risk_score": risk_score,
            "reasons": reasons,
        }

    # --------------------------------------------------
    # READINESS CHECK (NO DECISION)
    # --------------------------------------------------
    def readiness_hint(self, sop_id: str) -> Optional[str]:
        sop = self._registry.get_sop(sop_id, mode="summary")
        if not sop:
            return None

        if sop.get("requires_confirmation"):
            return "Ovaj SOP zahtijeva eksplicitnu potvrdu prije izvršenja."

        return "SOP je standardan i spreman za razmatranje."
