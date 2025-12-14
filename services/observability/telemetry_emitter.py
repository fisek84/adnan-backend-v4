from datetime import datetime
import logging

from services.observability.telemetry_event import TelemetryEvent
from services.observability.telemetry_sink import TelemetrySink, StdoutTelemetrySink

logger = logging.getLogger(__name__)


class TelemetryEmitter:
    """
    Passive telemetry emitter.

    FAZA 10.3 — OBSERVABILITY HARDENING

    RULES:
    - telemetry errors NEVER break execution
    - telemetry errors are ALWAYS visible
    - no silent failures
    """

    def __init__(self, sink: TelemetrySink | None = None):
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
        details: dict | None = None,
    ) -> None:
        """
        status: healthy | busy | degraded | failed
        """

        event = TelemetryEvent(
            event_type="agent_heartbeat",
            payload={
                "agent_id": agent_id,
                "status": status,
                "details": details or {},
                "timestamp": datetime.utcnow().isoformat(),
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
    ) -> None:
        """
        phase: started | completed | failed
        """

        event = TelemetryEvent(
            event_type="agent_execution",
            payload={
                "agent_id": agent_id,
                "task_id": task_id,
                "phase": phase,
                "timestamp": datetime.utcnow().isoformat(),
            },
        )

        self.emit(event)
