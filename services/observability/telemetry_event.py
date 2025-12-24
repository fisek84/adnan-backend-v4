# services/observability/telemetry_event.py

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class TelemetryEvent:
    """
    Canonical telemetry event.

    FAZA 8:
    - execution visibility
    - agent health / load
    - audit-grade event structure
    """

    ts: float
    event_type: str
    csi_state: str

    # optional high-level context
    intent: Optional[str] = None
    action: Optional[str] = None

    # structured payload
    payload: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        # Ensure payload is always a dict to simplify downstream consumers.
        object.__setattr__(self, "payload", self.payload or {})

    # -------------------------------------------------
    # FACTORY
    # -------------------------------------------------
    @staticmethod
    def now(
        *,
        event_type: str,
        csi_state: str,
        intent: Optional[str] = None,
        action: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> "TelemetryEvent":
        return TelemetryEvent(
            ts=time.time(),
            event_type=event_type,
            csi_state=csi_state,
            intent=intent,
            action=action,
            payload=payload,
        )

    # -------------------------------------------------
    # AGENT LOAD EVENT (HELPER)
    # -------------------------------------------------
    @staticmethod
    def agent_load(
        *,
        agent_id: str,
        current_load: int,
        max_concurrency: int,
        csi_state: str,
    ) -> "TelemetryEvent":
        return TelemetryEvent.now(
            event_type="agent_load",
            csi_state=csi_state,
            payload={
                "agent_id": agent_id,
                "current_load": int(current_load),
                "max_concurrency": int(max_concurrency),
            },
        )
