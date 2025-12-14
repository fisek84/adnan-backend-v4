# services/observability/telemetry_event.py

from dataclasses import dataclass
from typing import Optional, Dict, Any
import time


@dataclass
class TelemetryEvent:
    """
    Canonical telemetry event.
    """
    ts: float
    event_type: str
    csi_state: str
    intent: Optional[str] = None
    action: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None

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
