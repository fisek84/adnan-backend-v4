# services/autonomy/loop_controller.py

from dataclasses import dataclass
from typing import Optional, Dict, Any

from services.conversation_state_service import CSIState


# ============================================================
# LOOP DECISION (DATA ONLY)
# ============================================================

@dataclass
class LoopResult:
    """
    Result of a single loop governance evaluation.
    Data-only, no side effects.
    """
    allow: bool
    decision: str
    reason: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


# ============================================================
# LOOP CONTROLLER (KANONSKI)
# ============================================================

class LoopController:
    """
    Deterministic autonomy loop governance controller.

    RULES:
    - Reads CSI state only
    - Does NOT mutate CSI
    - Does NOT execute anything
    - Does NOT suggest actions
    - Emits governance decisions only
    """

    MAX_ITERATIONS = 5

    # --------------------------------------------------------
    # ENTRY GUARD
    # --------------------------------------------------------
    def can_start_loop(self, csi_state: str) -> bool:
        """
        Determines whether autonomy loop evaluation
        is allowed to run for the given CSI state.
        """
        try:
            state = CSIState(csi_state)
        except Exception:
            return False

        # Conservative: only explicit AUTONOMOUS_LOOP
        return state == CSIState.AUTONOMOUS_LOOP

    # --------------------------------------------------------
    # LOOP GOVERNANCE STEP
    # --------------------------------------------------------
    def run_step(
        self,
        *,
        iteration: int,
        csi_state: str,
        last_result: Optional[Dict[str, Any]] = None,
    ) -> LoopResult:
        """
        Evaluates a single autonomy loop governance step.
        """

        # -------------------------------
        # ITERATION LIMIT GUARD
        # -------------------------------
        if iteration >= self.MAX_ITERATIONS:
            return LoopResult(
                allow=False,
                decision="BLOCK",
                reason="max_iterations_reached",
                metadata={"iteration": iteration},
            )

        # -------------------------------
        # CSI VALIDATION
        # -------------------------------
        try:
            state = CSIState(csi_state)
        except Exception:
            return LoopResult(
                allow=False,
                decision="BLOCK",
                reason="invalid_csi_state",
            )

        # -------------------------------
        # STATE GOVERNANCE
        # -------------------------------
        if state != CSIState.AUTONOMOUS_LOOP:
            return LoopResult(
                allow=False,
                decision="BLOCK",
                reason="loop_not_allowed_from_state",
                metadata={"state": state.value},
            )

        # -------------------------------
        # GOVERNANCE ALLOW
        # -------------------------------
        return LoopResult(
            allow=True,
            decision="ALLOW",
            reason="loop_allowed",
            metadata={
                "iteration": iteration,
                "state": state.value,
                "last_result": last_result,
            },
        )
