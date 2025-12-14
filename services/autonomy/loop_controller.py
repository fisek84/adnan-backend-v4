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

    FAZA 8 / #21:
    - CSI-guarded
    - hard iteration limits
    - no implicit re-entry
    """

    MAX_ITERATIONS = 5

    # --------------------------------------------------------
    # ENTRY GUARD (HARD CSI CHECK)
    # --------------------------------------------------------
    def can_start_loop(self, csi_state: str) -> bool:
        try:
            return CSIState(csi_state) == CSIState.AUTONOMOUS_LOOP
        except Exception:
            return False

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

        # -------------------------------
        # HARD CSI GUARD
        # -------------------------------
        if not self.can_start_loop(csi_state):
            return LoopResult(
                allow=False,
                decision="BLOCK",
                reason="csi_state_not_autonomous",
                metadata={"state": csi_state},
            )

        # -------------------------------
        # ITERATION LIMIT
        # -------------------------------
        if iteration >= self.MAX_ITERATIONS:
            return LoopResult(
                allow=False,
                decision="STOP",
                reason="max_iterations_reached",
                metadata={"iteration": iteration},
            )

        # -------------------------------
        # LOOP ALLOW
        # -------------------------------
        return LoopResult(
            allow=True,
            decision="ALLOW",
            reason="loop_allowed",
            metadata={
                "iteration": iteration,
                "state": csi_state,
                "last_result": last_result,
            },
        )
