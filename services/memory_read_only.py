# services/memory_read_only.py
from __future__ import annotations

from typing import Any, Dict, Optional

from services.memory_service import MemoryService


class ReadOnlyMemoryService:
    """
    CANONICAL: Read-only adapter over MemoryService.

    Goal:
    - LLM/Advisory layers may READ decision history, KPI trends, evaluations
    - LLM/Advisory layers must NOT be able to WRITE to memory through this object

    Design:
    - Exposes ONLY MemoryService.get(...) and selected safe read-only helpers
    - Does NOT expose .set/.delete/.process/.store_* or raw .memory dict
    """

    def __init__(self, memory_service: Optional[MemoryService] = None) -> None:
        self._mem = memory_service or MemoryService()

    # ----------------------------
    # Canonical scoped read
    # ----------------------------
    def get(
        self,
        *,
        scope_type: str,
        scope_id: str,
        key: str,
        default: Any = None,
    ) -> Any:
        return self._mem.get(
            scope_type=scope_type,
            scope_id=scope_id,
            key=key,
            default=default,
        )

    # ----------------------------
    # Minimal read-only export (for LLM context)
    # ----------------------------
    def export_public_snapshot(self) -> Dict[str, Any]:
        raw = getattr(self._mem, "memory", {})
        if not isinstance(raw, dict):
            return {}

        memory_items = raw.get("memory_items")
        items_count = 0
        if isinstance(memory_items, list):
            items_count = len([x for x in memory_items if isinstance(x, dict)])

        return {
            "schema_version": raw.get("schema_version"),
            "decision_outcomes": list(raw.get("decision_outcomes") or []),
            "execution_stats": dict(raw.get("execution_stats") or {}),
            "write_audit_events": list(raw.get("write_audit_events") or []),
            "active_decision": raw.get("active_decision"),
            "memory_items_count": items_count,
            "last_memory_write": raw.get("last_memory_write"),
        }

    # ----------------------------
    # Legacy read-only helpers
    # ----------------------------
    def get_active_decision(self) -> Any:
        return self._mem.get_active_decision()

    def get_recent(self, limit: int = 10) -> Any:
        return self._mem.get_recent(limit=limit)

    def sop_success_rate(self, sop_key: str) -> float:
        return self._mem.sop_success_rate(sop_key)

    # Hard fail on attribute access to anything else (defensive)
    def __getattr__(self, name: str) -> Any:
        raise AttributeError(f"ReadOnlyMemoryService does not expose attribute: {name}")
