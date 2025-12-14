# services/observability/telemetry_event.py

from dataclasses import dataclass
from typing import Optional, Dict, Any
import time


@dataclass
class TelemetryEvent:
    """
    Canonical telemetry event.

    FAZA 7:
    - agent health
    - agent load
    - execution visibility
    """

    ts: float
    event_type: str
    csi_state: str

    # optional high-level context
    intent: Optional[str] = None
    action: Optional[str] = None

    # structured payload
    payload: Optional[Dict[str, Any]] = None

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
        return TelemetryEvent(
            ts=time.time(),
            event_type="agent_load",
            csi_state=csi_state,
            payload={
                "agent_id": agent_id,
                "current_load": current_load,
                "max_concurrency": max_concurrency,
            },
        )
