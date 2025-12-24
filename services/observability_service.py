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

from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.memory_service import MemoryService


class ObservabilityService:
    def __init__(self, memory_service: Optional[MemoryService] = None):
        # READ-ONLY: ObservabilityService ne smije raditi write/mutaciju.
        self.memory: MemoryService = memory_service or MemoryService()

    # ============================================================
    # INTERNAL SAFE READ HELPERS (defanzivno, read-only)
    # ============================================================
    def _get_memory_dict(self, key: str) -> Dict[str, Any]:
        raw = getattr(self.memory, "memory", {})
        if not isinstance(raw, dict):
            return {}

        value = raw.get(key, {})
        if isinstance(value, dict):
            return value
        return {}

    def _get_memory_list_of_dicts(self, key: str) -> List[Dict[str, Any]]:
        raw = getattr(self.memory, "memory", {})
        if not isinstance(raw, dict):
            return []

        value = raw.get(key, [])
        if not isinstance(value, list):
            return []

        out: List[Dict[str, Any]] = []
        for item in value:
            if isinstance(item, dict):
                out.append(item)
        return out

    # ============================================================
    # ACTIVE DECISION
    # ============================================================
    def get_active_decision(self) -> Optional[Dict[str, Any]]:
        return self.memory.get_active_decision()

    # ============================================================
    # EXECUTION STATS
    # ============================================================
    def get_execution_stats(
        self,
        decision_type: Optional[str] = None,
        key: Optional[str] = None,
    ) -> Dict[str, Any]:
        stats = self._get_memory_dict("execution_stats")

        if decision_type and key:
            value = stats.get(f"{decision_type}:{key}", {})
            return value if isinstance(value, dict) else {}

        if decision_type:
            return {
                k: v
                for k, v in stats.items()
                if isinstance(k, str) and k.startswith(f"{decision_type}:")
            }

        return stats

    # ============================================================
    # DECISION OUTCOMES (AUDIT TRAIL)
    # ============================================================
    def get_decision_outcomes(
        self,
        limit: int = 50,
        decision_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        outcomes = self._get_memory_list_of_dicts("decision_outcomes")

        if decision_type:
            outcomes = [o for o in outcomes if o.get("decision_type") == decision_type]

        if limit <= 0:
            return []

        return outcomes[-limit:]

    # ============================================================
    # SOP PERFORMANCE
    # ============================================================
    def get_sop_performance(self, sop_key: str) -> Dict[str, Any]:
        relations = self._get_memory_dict("cross_sop_relations")

        related: Dict[str, Any] = {
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
    # SYSTEM SNAPSHOT (UI FRIENDLY)
    # ============================================================
    def get_system_snapshot(self) -> Dict[str, Any]:
        return {
            "active_decision": self.get_active_decision(),
            "recent_decisions": self.get_decision_outcomes(limit=10),
            "execution_stats": self.get_execution_stats(),
            "read_only": True,
        }
