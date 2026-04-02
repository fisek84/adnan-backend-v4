from __future__ import annotations

from threading import Lock
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from services.approval_state_service import _utc_now_iso


class AuditEvent(BaseModel):
    event_type: str
    request_id: str

    principal_sub: Optional[str] = None
    principal_roles: List[str] = Field(default_factory=list)

    route: Optional[str] = None
    result: Optional[str] = None

    approval_id: Optional[str] = None
    execution_id: Optional[str] = None

    timestamp_utc: str = Field(default_factory=_utc_now_iso)
    data: Dict[str, Any] = Field(default_factory=dict)


class AuditLogService:
    """Central audit event collector (in-process).

    Contract:
    - emit() must not raise (best-effort) so critical paths remain deterministic.
    - storage is in-memory only (no external observability systems).
    """

    def __init__(self) -> None:
        self._events: List[AuditEvent] = []
        self._lock = Lock()

    def emit(self, event: AuditEvent) -> None:
        try:
            if not isinstance(event, AuditEvent):
                return
            with self._lock:
                self._events.append(event)
        except Exception:
            return

    def list_events(self) -> List[AuditEvent]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


_AUDIT_LOG_SINGLETON = AuditLogService()


def get_audit_log_service() -> AuditLogService:
    return _AUDIT_LOG_SINGLETON
