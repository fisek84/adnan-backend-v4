# services/autonomy/failure_handler.py

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

from services.autonomy.recovery_strategy import RecoveryAction, RecoveryResult
from services.autonomy.self_check import SelfCheckResult, SelfCheckStatus


# ============================================================
# FAILURE OUTCOME (KANONSKI)
# ============================================================


class FailureOutcome(Enum):
    CONTINUE = "continue"
    FALLBACK = "fallback"
    ABORT = "abort"
    IDLE = "idle"


# ============================================================
# FAILURE HANDLING RESULT (DATA ONLY)
# ============================================================


@dataclass
class FailureHandlingResult:
    """
    Result of failure handling evaluation.
    Data-only, no side effects.
    """

    outcome: FailureOutcome
    reason: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# ============================================================
# FAILURE HANDLER (KANONSKI)
# ============================================================


class FailureHandler:
    """
    Deterministic failure & recovery handler.

    RULES:
    - No CSI mutation
    - No execution
    - No automatic retry
    - Data-only advisory signals
    """

    def handle(
        self,
        *,
        self_check: Optional[SelfCheckResult],
        recovery: Optional[RecoveryResult],
    ) -> FailureHandlingResult:
        """
        Determines final advisory outcome after self-check and recovery evaluation.
        """

        # -------------------------------
        # NO SELF-CHECK → SAFE ABORT
        # -------------------------------
        if self_check is None:
            return FailureHandlingResult(
                outcome=FailureOutcome.ABORT,
                reason="no_self_check_result",
            )

        # -------------------------------
        # SUCCESS → CONTINUE
        # -------------------------------
        if self_check.status == SelfCheckStatus.SUCCESS:
            return FailureHandlingResult(
                outcome=FailureOutcome.CONTINUE,
                reason="self_check_success",
            )

        # -------------------------------
        # RECOVERY REQUIRED
        # -------------------------------
        if recovery is None:
            return FailureHandlingResult(
                outcome=FailureOutcome.ABORT,
                reason="no_recovery_decision",
            )

        # -------------------------------
        # RETRY IS ADVISORY ONLY (NO ACTION)
        # -------------------------------
        if recovery.action == RecoveryAction.RETRY:
            return FailureHandlingResult(
                outcome=FailureOutcome.CONTINUE,
                reason="retry_proposed",
                metadata=recovery.metadata,
            )

        if recovery.action == RecoveryAction.FALLBACK:
            return FailureHandlingResult(
                outcome=FailureOutcome.FALLBACK,
                reason=recovery.reason,
                metadata=recovery.metadata,
            )

        if recovery.action == RecoveryAction.IDLE:
            return FailureHandlingResult(
                outcome=FailureOutcome.IDLE,
                reason=recovery.reason,
            )

        # -------------------------------
        # DEFAULT → ABORT
        # -------------------------------
        return FailureHandlingResult(
            outcome=FailureOutcome.ABORT,
            reason="unhandled_failure_case",
        )
