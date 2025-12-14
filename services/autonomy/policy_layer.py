# services/autonomy/policy_layer.py

from dataclasses import dataclass
from enum import Enum
from typing import Optional, Dict, Any

from services.conversation_state_service import CSIState


# ============================================================
# POLICY DECISION (KANONSKI)
# ============================================================

class PolicyDecision(Enum):
    ALLOW = "allow"
    DENY = "deny"


# ============================================================
# POLICY RESULT (DATA ONLY)
# ============================================================

@dataclass
class PolicyResult:
    """
    Result of a policy evaluation.
    Data-only, no side effects.
    """
    decision: PolicyDecision
    reason: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# ============================================================
# AUTONOMY POLICY LAYER (KANONSKI)
# ============================================================

class AutonomyPolicy:
    """
    Deterministic policy layer for autonomy.

    RULES:
    - No CSI mutation
    - No execution
    - No retries
    - Policy is read-only governance
    """

    MAX_AUTONOMY_ITERATIONS = 5

    def evaluate(
        self,
        *,
        csi_state: str,
        iteration: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> PolicyResult:
        """
        Evaluates whether autonomy is allowed to proceed.
        """

        # -------------------------------
        # CSI STATE GUARD
        # -------------------------------
        try:
            state = CSIState(csi_state)
        except Exception:
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason="invalid_csi_state",
            )

        # Conservative: policy never re-opens autonomy
        if state != CSIState.AUTONOMOUS_LOOP:
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason="state_not_allowed_for_autonomy",
                metadata={"state": state.value},
            )

        # -------------------------------
        # ITERATION LIMIT
        # -------------------------------
        if iteration >= self.MAX_AUTONOMY_ITERATIONS:
            return PolicyResult(
                decision=PolicyDecision.DENY,
                reason="autonomy_iteration_limit_reached",
                metadata={
                    "iteration": iteration,
                    "max": self.MAX_AUTONOMY_ITERATIONS,
                },
            )

        # -------------------------------
        # DEFAULT ALLOW
        # -------------------------------
        return PolicyResult(
            decision=PolicyDecision.ALLOW,
            reason="policy_allow",
        )
