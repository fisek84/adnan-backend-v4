# services/autonomy/self_check.py

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any


# ============================================================
# SELF-CHECK STATUS (KANONSKI)
# ============================================================


class SelfCheckStatus(Enum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNKNOWN = "unknown"


# ============================================================
# SELF-CHECK RESULT (DATA ONLY)
# ============================================================


@dataclass
class SelfCheckResult:
    """
    Result of a self-check evaluation.
    Data-only, no side effects.
    """

    status: SelfCheckStatus
    reason: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# ============================================================
# SELF-CHECK EVALUATOR (KANONSKI)
# ============================================================


class SelfCheckEvaluator:
    """
    Deterministic self-check evaluator.

    RULES:
    - No CSI mutation
    - No execution
    - No retries
    - Defensive, data-only evaluation
    """

    def evaluate(
        self,
        *,
        expected_outcome: Optional[Dict[str, Any]],
        actual_result: Optional[Dict[str, Any]] = None,
    ) -> SelfCheckResult:
        """
        Evaluates whether the expected outcome was achieved.
        """

        # -------------------------------
        # DEFENSIVE INPUT VALIDATION
        # -------------------------------
        if not expected_outcome or not isinstance(expected_outcome, dict):
            return SelfCheckResult(
                status=SelfCheckStatus.UNKNOWN,
                reason="invalid_or_missing_expected_outcome",
            )

        if actual_result is None:
            return SelfCheckResult(
                status=SelfCheckStatus.UNKNOWN,
                reason="no_result_available",
            )

        # -------------------------------
        # BASIC KEY MATCH CHECK
        # -------------------------------
        for key, expected_value in expected_outcome.items():
            actual_value = actual_result.get(key)
            if actual_value != expected_value:
                return SelfCheckResult(
                    status=SelfCheckStatus.FAILURE,
                    reason="expected_outcome_mismatch",
                    metadata={
                        "key": key,
                        "expected": expected_value,
                        "actual": actual_value,
                    },
                )

        return SelfCheckResult(
            status=SelfCheckStatus.SUCCESS,
            reason="expected_outcome_met",
        )
