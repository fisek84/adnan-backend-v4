"""
AUDIT SERVICE — FAZA 9 (INCIDENT REVIEW)

Uloga:
- centralni audit uvid
- incident-centric snapshot
- READ-ONLY
- nema izvršenja
- nema mutacije stanja
"""

from typing import Dict, Any, List, Optional
from services.memory_service import MemoryService


class AuditService:
    def __init__(self):
        self.memory = MemoryService()  # READ-ONLY

    # ============================================================
    # GENERAL AUDIT LOG
    # ============================================================
    def get_audit_log(
        self,
        limit: int = 100,
        decision_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:

        records = self.memory.memory.get("decision_outcomes", [])

        if decision_type:
            records = [
                r for r in records
                if r.get("decision_type") == decision_type
            ]

        return records[-limit:]

    # ============================================================
    # EXECUTION AUDIT
    # ============================================================
    def get_execution_audit(
        self,
        decision_type: Optional[str] = None,
        key: Optional[str] = None,
    ) -> Dict[str, Any]:

        stats = self.memory.memory.get("execution_stats", {})

        if decision_type and key:
            return stats.get(f"{decision_type}:{key}", {})

        if decision_type:
            return {
                k: v for k, v in stats.items()
                if k.startswith(f"{decision_type}:")
            }

        return stats

    # ============================================================
    # SOP AUDIT
    # ============================================================
    def get_sop_audit(self, sop_key: str) -> Dict[str, Any]:
        return {
            "sop": sop_key,
            "success_rate": self.memory.sop_success_rate(sop_key),
            "cross_sop_relations": self.memory.get_cross_sop_bias(sop_key),
            "read_only": True,
        }

    # ============================================================
    # ACTIVE DECISION
    # ============================================================
    def get_active_decision(self) -> Optional[Dict[str, Any]]:
        return self.memory.get_active_decision()

    # ============================================================
    # INCIDENT REVIEW (FAZA 9 / #29)
    # ============================================================
    def get_incidents(
        self,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Incident = failed / blocked / escalated outcome
        """

        incidents = []

        for r in self.memory.memory.get("decision_outcomes", []):
            if r.get("status") in {"failed", "blocked", "escalated"}:
                incidents.append(r)

        return incidents[-limit:]

    # ============================================================
    # FULL AUDIT SNAPSHOT
    # ============================================================
    def get_full_audit_snapshot(self) -> Dict[str, Any]:
        """
        Compliance / enterprise snapshot
        """
        return {
            "active_decision": self.get_active_decision(),
            "decision_outcomes": self.get_audit_log(limit=50),
            "incidents": self.get_incidents(limit=20),
            "execution_stats": self.get_execution_audit(),
            "read_only": True,
        }
