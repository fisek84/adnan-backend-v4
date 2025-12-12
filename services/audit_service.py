# services/audit_service.py

"""
AUDIT SERVICE — FAZA 12 (READ-ONLY)

Uloga:
- centralni audit uvid u:
  - decision outcomes
  - execution history
  - SOP rezultate
  - sigurnosne / blokirane ishode
- koristi isključivo MemoryService
- nema izvršenja
- nema pisanja
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
        """
        Vraća audit log (decision_outcomes).
        Može se filtrirati po decision_type.
        """

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
        """
        Vraća execution audit (execution_stats).
        """

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
        """
        Audit za konkretan SOP:
        - success rate
        - cross-SOP relacije
        """

        return {
            "sop": sop_key,
            "success_rate": self.memory.sop_success_rate(sop_key),
            "cross_sop_relations": self.memory.get_cross_sop_bias(sop_key),
            "read_only": True,
        }

    # ============================================================
    # ACTIVE DECISION AUDIT
    # ============================================================
    def get_active_decision(self) -> Optional[Dict[str, Any]]:
        """
        Trenutno aktivna odluka (ako postoji).
        """
        return self.memory.get_active_decision()

    # ============================================================
    # FULL AUDIT SNAPSHOT
    # ============================================================
    def get_full_audit_snapshot(self) -> Dict[str, Any]:
        """
        Jedan poziv za compliance / enterprise audit.
        """
        return {
            "active_decision": self.get_active_decision(),
            "decision_outcomes": self.get_audit_log(limit=50),
            "execution_stats": self.get_execution_audit(),
            "read_only": True,
        }
