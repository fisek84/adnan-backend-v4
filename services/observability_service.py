# services/observability_service.py

"""
OBSERVABILITY & AUDIT SURFACE — FAZA 12 (READ-ONLY)

Uloga:
- centralni read-only uvid u:
  - aktivnu odluku
  - execution statistike
  - decision outcomes
  - SOP performanse
- koristi postojeći MemoryService
- nema izvršenja
- nema pisanja
- nema mutacije stanja
"""

from typing import Dict, Any, List, Optional
from services.memory_service import MemoryService


class ObservabilityService:
    def __init__(self):
        self.memory = MemoryService()  # READ-ONLY

    # ============================================================
    # ACTIVE DECISION
    # ============================================================
    def get_active_decision(self) -> Optional[Dict[str, Any]]:
        """
        Trenutno aktivna (potvrđena) odluka, ako postoji.
        """
        return self.memory.get_active_decision()

    # ============================================================
    # EXECUTION STATS
    # ============================================================
    def get_execution_stats(
        self,
        decision_type: Optional[str] = None,
        key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Vraća execution statistiku.
        Ako nije specificiran key → vraća sve.
        """

        stats = self.memory.memory.get("execution_stats", {})

        if decision_type and key:
            entry = stats.get(f"{decision_type}:{key}")
            return entry or {}

        return stats

    # ============================================================
    # DECISION OUTCOMES (AUDIT TRAIL)
    # ============================================================
    def get_decision_outcomes(
        self,
        limit: int = 50,
        decision_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Audit trail odluka i izvršenja.
        """
        outcomes = self.memory.memory.get("decision_outcomes", [])

        if decision_type:
            outcomes = [
                o for o in outcomes
                if o.get("decision_type") == decision_type
            ]

        return outcomes[-limit:]

    # ============================================================
    # SOP PERFORMANCE
    # ============================================================
    def get_sop_performance(self, sop_key: str) -> Dict[str, Any]:
        """
        READ-ONLY SOP success rate + chaining bias.
        """
        return {
            "sop": sop_key,
            "success_rate": self.memory.sop_success_rate(sop_key),
            "next_sop_bias": self.memory.get_cross_sop_bias(sop_key),
        }

    # ============================================================
    # SYSTEM SNAPSHOT (UI FRIENDLY)
    # ============================================================
    def get_system_snapshot(self) -> Dict[str, Any]:
        """
        Jedan poziv za CEO / UI dashboard.
        """
        return {
            "active_decision": self.get_active_decision(),
            "recent_decisions": self.get_decision_outcomes(limit=10),
            "execution_stats": self.get_execution_stats(),
            "read_only": True,
        }
