# services/observability/telemetry_sink.py

from typing import Protocol
import json
from services.observability.telemetry_event import TelemetryEvent


class TelemetrySink(Protocol):
    def emit(self, event: TelemetryEvent) -> None: ...


class StdoutTelemetrySink:
    """
    Default sink – prints telemetry (structured, audit-safe).
    """

    def emit(self, event: TelemetryEvent) -> None:
        try:
            print(
                "[TELEMETRY]",
                json.dumps(
                    {
                        "ts": event.ts,
                        "event_type": event.event_type,
                        "csi_state": event.csi_state,
                        "intent": event.intent,
                        "action": event.action,
                        "payload": event.payload,
                    },
                    ensure_ascii=False,
                ),
            )
        except Exception:
            # telemetry must never break runtime
            pass
