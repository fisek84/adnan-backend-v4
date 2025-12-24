# services/observability/telemetry_sink.py

from __future__ import annotations

import json
import logging
from typing import Protocol

from services.observability.telemetry_event import TelemetryEvent


logger = logging.getLogger(__name__)


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
        except Exception as e:
            # telemetry must never break runtime, but failure should be visible
            logger.error("STDOUT TELEMETRY SINK FAILED | error=%s", str(e))
