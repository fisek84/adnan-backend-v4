from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

from services.conversation_state_service import CSIState
from services.autonomy.self_check import SelfCheckStatus


# ============================================================
# RECOVERY ACTION (KANONSKI)
# ============================================================


class RecoveryAction(Enum):
    ABORT = "abort"
    FALLBACK = "fallback"
    IDLE = "idle"


# ============================================================
# RECOVERY RESULT (DATA ONLY)
# ============================================================


@dataclass
class RecoveryResult:
    """
    Result of a recovery evaluation.
    Data-only, no side effects.
    """

    action: RecoveryAction
    reason: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# ============================================================
# RECOVERY STRATEGY (FAZA 5 – DATA ONLY)
# ============================================================


class RecoveryStrategy:
    """
    Deterministic recovery proposal generator.

    RULES:
    - No CSI mutation
    - No execution
    - No retry actions
    - Data-only advisory output
    """

    MAX_RETRIES = 2

    def decide(
        self,
        *,
        csi_state: str,
        self_check_status: SelfCheckStatus,
        retry_count: int,
        last_error: Optional[str] = None,
    ) -> RecoveryResult:
        """
        Determines a recovery advisory signal.
        """

        # Validate CSI state; if nevažeći → safe ABORT
        try:
            CSIState(csi_state)
        except Exception:
            return RecoveryResult(
                action=RecoveryAction.ABORT,
                reason="invalid_csi_state",
                metadata={"raw_csi_state": csi_state},
            )

        # -------------------------------
        # SUCCESS → NO RECOVERY
        # -------------------------------
        if self_check_status == SelfCheckStatus.SUCCESS:
            return RecoveryResult(
                action=RecoveryAction.IDLE,
                reason="no_recovery_needed",
            )

        # -------------------------------
        # UNKNOWN → SAFE ABORT
        # -------------------------------
        if self_check_status == SelfCheckStatus.UNKNOWN:
            return RecoveryResult(
                action=RecoveryAction.ABORT,
                reason="outcome_unknown",
            )

        # -------------------------------
        # FAILURE → ADVISORY FALLBACK
        # -------------------------------
        if self_check_status == SelfCheckStatus.FAILURE:
            return RecoveryResult(
                action=RecoveryAction.FALLBACK,
                reason="failure_detected",
                metadata={
                    "retry_count": retry_count,
                    "max_retries": self.MAX_RETRIES,
                    "last_error": last_error,
                    "retry_possible": retry_count < self.MAX_RETRIES,
                },
            )

        # -------------------------------
        # DEFAULT SAFE ABORT
        # -------------------------------
        return RecoveryResult(
            action=RecoveryAction.ABORT,
            reason="unhandled_recovery_case",
        )
