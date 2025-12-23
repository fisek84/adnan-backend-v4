# services/autonomy/telemetry.py

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any
from datetime import datetime, timezone


# ============================================================
# TELEMETRY EVENT TYPE (KANONSKI)
# ============================================================


class TelemetryEventType(Enum):
    LOOP_EVALUATED = "loop_evaluated"
    POLICY_EVALUATED = "policy_evaluated"
    SELF_CHECK_EVALUATED = "self_check_evaluated"
    RECOVERY_EVALUATED = "recovery_evaluated"
    AUTONOMY_CYCLE_EVALUATED = "autonomy_cycle_evaluated"


# ============================================================
# TELEMETRY EVENT (DATA ONLY)
# ============================================================


@dataclass
class TelemetryEvent:
    """
    Structured telemetry event.
    Data-only, no side effects.
    """

    event_type: TelemetryEventType
    ts: str
    payload: Optional[Dict[str, Any]] = None


# ============================================================
# AUTONOMY TELEMETRY (KANONSKI)
# ============================================================


class AutonomyTelemetry:
    """
    Deterministic autonomy telemetry emitter.

    RULES:
    - No CSI mutation
    - No execution
    - No decisions
    - Emits governance-level evaluation events only
    """

    def emit(
        self,
        *,
        event_type: TelemetryEventType,
        payload: Optional[Dict[str, Any]] = None,
    ) -> TelemetryEvent:
        """
        Emits a telemetry evaluation event.
        """

        return TelemetryEvent(
            event_type=event_type,
            ts=datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            payload=payload or {},
        )
