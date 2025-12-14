# services/observability/telemetry_sink.py

from typing import Protocol
from services.observability.telemetry_event import TelemetryEvent


class TelemetrySink(Protocol):
    def emit(self, event: TelemetryEvent) -> None:
        ...


class StdoutTelemetrySink:
    """
    Default sink – prints telemetry.
    """

    def emit(self, event: TelemetryEvent) -> None:
        print("[TELEMETRY]", event)
