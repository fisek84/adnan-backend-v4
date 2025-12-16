# services/observability/telemetry_emitter.py

import logging
from typing import Optional, Dict, Any

from services.observability.telemetry_event import TelemetryEvent
from services.observability.telemetry_sink import TelemetrySink, StdoutTelemetrySink

logger = logging.getLogger(__name__)


class TelemetryEmitter:
    """
    Passive telemetry emitter.

    FAZA 8 — TELEMETRY / AUDIT

    RULES:
    - telemetry errors NEVER break execution
    - telemetry errors are ALWAYS visible
    - no silent failures
    """

    def __init__(self, sink: Optional[TelemetrySink] = None):
        self.sink = sink or StdoutTelemetrySink()

    # -------------------------------------------------
    # GENERIC EMIT (HARDENED)
    # -------------------------------------------------
    def emit(self, event: TelemetryEvent) -> None:
        try:
            self.sink.emit(event)
        except Exception as e:
            logger.error(
                "TELEMETRY EMIT FAILED | event_type=%s | error=%s",
                getattr(event, "event_type", "unknown"),
                str(e),
            )

    # -------------------------------------------------
    # AGENT HEALTH — HEARTBEAT
    # -------------------------------------------------
    def emit_agent_heartbeat(
        self,
        *,
        agent_id: str,
        status: str,
        csi_state: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        status: healthy | busy | degraded | failed
        """

        event = TelemetryEvent.now(
            event_type="agent_heartbeat",
            csi_state=csi_state,
            payload={
                "agent_id": agent_id,
                "status": status,
                "details": details or {},
            },
        )

        self.emit(event)

    # -------------------------------------------------
    # AGENT EXECUTION SIGNAL
    # -------------------------------------------------
    def emit_agent_execution(
        self,
        *,
        agent_id: str,
        task_id: str,
        phase: str,
        csi_state: str,
    ) -> None:
        """
        phase: started | completed | failed
        """

        event = TelemetryEvent.now(
            event_type="agent_execution",
            csi_state=csi_state,
            payload={
                "agent_id": agent_id,
                "task_id": task_id,
                "phase": phase,
            },
        )

        self.emit(event)
