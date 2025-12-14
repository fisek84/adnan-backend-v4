# services/observability/telemetry_emitter.py

from services.observability.telemetry_event import TelemetryEvent
from services.observability.telemetry_sink import TelemetrySink, StdoutTelemetrySink


class TelemetryEmitter:
    """
    Passive telemetry emitter.
    """

    def __init__(self, sink: TelemetrySink | None = None):
        self.sink = sink or StdoutTelemetrySink()

    def emit(self, event: TelemetryEvent) -> None:
        try:
            self.sink.emit(event)
        except Exception:
            pass
