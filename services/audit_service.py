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

from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.memory_service import MemoryService


class AuditService:
    def __init__(self, memory_service: Optional[MemoryService] = None):
        # READ-ONLY
        self.memory: MemoryService = memory_service or MemoryService()

    # ============================================================
    # INTERNAL SAFE READ HELPERS (defanzivno, read-only)
    # ============================================================
    def _get_memory_dict(self, key: str) -> Dict[str, Any]:
        raw = getattr(self.memory, "memory", {})
        if not isinstance(raw, dict):
            return {}
        value = raw.get(key, {})
        return value if isinstance(value, dict) else {}

    def _get_memory_list(self, key: str) -> List[Any]:
        raw = getattr(self.memory, "memory", {})
        if not isinstance(raw, dict):
            return []
        value = raw.get(key, [])
        return value if isinstance(value, list) else []

    def _get_memory_list_of_dicts(self, key: str) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for item in self._get_memory_list(key):
            if isinstance(item, dict):
                out.append(item)
        return out

    # ============================================================
    # GENERAL AUDIT LOG
    # ============================================================
    def get_audit_log(
        self,
        limit: int = 100,
        decision_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        records = list(self._get_memory_list_of_dicts("decision_outcomes"))

        if decision_type:
            records = [r for r in records if r.get("decision_type") == decision_type]

        if limit <= 0:
            return []

        return records[-limit:]

    # ============================================================
    # WRITE AUDIT (PHASE 5+)
    # ============================================================
    def get_write_audit_events(
        self,
        limit: int = 100,
        event_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        records = list(self._get_memory_list_of_dicts("write_audit_events"))

        if event_type:
            records = [r for r in records if r.get("event_type") == event_type]

        if limit <= 0:
            return []

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

        stats = self._get_memory_dict("execution_stats")

        if context_type and directive:
            entry = stats.get(f"{context_type}:{directive}", {}) or {}
            return entry if isinstance(entry, dict) else {}

        if context_type:
            prefix = f"{context_type}:"
            return {
                k: v
                for k, v in stats.items()
                if isinstance(k, str) and k.startswith(prefix)
            }

        return stats

    # ============================================================
    # EXECUTION KPI SNAPSHOT (AGGREGATED)
    # ============================================================
    def get_execution_kpis(self) -> Dict[str, Any]:
        """
        Aggregated execution KPIs across all directives.
        """

        stats = self._get_memory_dict("execution_stats")

        total = 0
        allowed = 0
        blocked = 0

        for entry in stats.values():
            if not isinstance(entry, dict):
                continue
            total += int(entry.get("total", 0))
            allowed += int(entry.get("allowed", 0))
            blocked += int(entry.get("blocked", 0))

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
        relations = self._get_memory_dict("cross_sop_relations")

        related = {
            k: v
            for k, v in relations.items()
            if isinstance(k, str)
            and (k.endswith(f"->{sop_key}") or k.startswith(f"{sop_key}->"))
        }

        return {
            "sop": sop_key,
            "success_rate": self.memory.sop_success_rate(sop_key),
            "cross_sop_relations": related,
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
        Incident = unsuccessful decision outcome
        """

        incidents = [
            r
            for r in self._get_memory_list_of_dicts("decision_outcomes")
            if r.get("success") is False
        ]

        if limit <= 0:
            return []

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
            "write_audit_events": self.get_write_audit_events(limit=50),
            "incidents": self.get_incidents(limit=20),
            "execution_stats": self.get_execution_audit(),
            "execution_kpis": self.get_execution_kpis(),
            "read_only": True,
        }
