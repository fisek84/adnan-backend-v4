# services/audit_service.py

"""
AUDIT SERVICE — FAZA 11 (EXECUTION AUDIT + KPI)

Uloga:
- centralni audit uvid
- execution + incident + KPI snapshot
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
    # EXECUTION AUDIT (RAW)
    # ============================================================
    def get_execution_audit(
        self,
        context_type: Optional[str] = None,
        directive: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Raw execution governance statistics.
        """

        stats = self.memory.memory.get("execution_stats", {})

        if context_type and directive:
            return stats.get(f"{context_type}:{directive}", {})

        if context_type:
            return {
                k: v for k, v in stats.items()
                if k.startswith(f"{context_type}:")
            }

        return stats

    # ============================================================
    # EXECUTION KPI SNAPSHOT (AGGREGATED)
    # ============================================================
    def get_execution_kpis(self) -> Dict[str, Any]:
        """
        Aggregated execution KPIs across all directives.
        """

        stats = self.memory.memory.get("execution_stats", {})

        total = 0
        allowed = 0
        blocked = 0

        for entry in stats.values():
            total += entry.get("total", 0)
            allowed += entry.get("allowed", 0)
            blocked += entry.get("blocked", 0)

        success_rate = (allowed / total) if total > 0 else None

        return {
            "total_decisions": total,
            "allowed": allowed,
            "blocked": blocked,
            "success_rate": success_rate,
            "read_only": True,
        }

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
    # INCIDENT REVIEW (FAILED / BLOCKED)
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
    # FULL AUDIT SNAPSHOT (COMPLIANCE)
    # ============================================================
    def get_full_audit_snapshot(self) -> Dict[str, Any]:
        """
        Enterprise / compliance snapshot
        """

        return {
            "active_decision": self.get_active_decision(),
            "decision_outcomes": self.get_audit_log(limit=50),
            "incidents": self.get_incidents(limit=20),
            "execution_stats": self.get_execution_audit(),
            "execution_kpis": self.get_execution_kpis(),
            "read_only": True,
        }
