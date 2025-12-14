# services/autonomy/autonomy_entrypoint.py

from typing import Dict, Any, Optional

from services.conversation_state_service import ConversationStateService, CSIState
from services.autonomy.autonomy_coordinator import AutonomyCoordinator, AutonomyCycleResult
from services.autonomy.policy_layer import AutonomyPolicy, PolicyDecision
from services.autonomy.loop_controller import LoopController
from services.autonomy.kill_switch import AutonomyKillSwitch
from services.autonomy.feature_flags import AutonomyFeatureFlags
from services.autonomy.safe_mode import AutonomySafeMode


class AutonomyEntryPoint:
    """
    Production-hardened autonomy entry point.

    ROLE:
    - Orchestrates autonomy evaluation flow
    - Enforces hard gates (kill-switch, safe-mode, policy, loop)
    - Does NOT evaluate
    - Does NOT mutate results
    """

    def __init__(
        self,
        conversation_state: ConversationStateService,
        *,
        kill_switch: AutonomyKillSwitch,
        feature_flags: AutonomyFeatureFlags,
        safe_mode: AutonomySafeMode,
    ):
        self.conversation_state = conversation_state

        self.policy = AutonomyPolicy()
        self.loop_controller = LoopController()
        self.coordinator = AutonomyCoordinator()

        self.kill_switch = kill_switch
        self.flags = feature_flags
        self.safe_mode = safe_mode

    # -------------------------------------------------
    # ENTRY GUARD
    # -------------------------------------------------
    def can_enter(self) -> bool:
        csi = self.conversation_state.get()
        try:
            return (
                self.kill_switch.is_enabled()
                and CSIState(csi.get("state")) == CSIState.AUTONOMOUS_LOOP
            )
        except Exception:
            return False

    # -------------------------------------------------
    # MAIN ENTRY
    # -------------------------------------------------
    def run(
        self,
        *,
        iteration: int,
        expected_outcome: Optional[Dict[str, Any]] = None,
        actual_result: Optional[Dict[str, Any]] = None,
        retry_count: int = 0,
        last_error: Optional[str] = None,
    ) -> Optional[AutonomyCycleResult]:

        # ---- HARD ENTRY GUARD
        if not self.can_enter():
            return None

        # ---- SAFE MODE
        if self.safe_mode.is_enabled():
            return None

        csi_state = self.conversation_state.get().get("state")

        # ---- LOOP GOVERNANCE
        loop_decision = self.loop_controller.run_step(
            iteration=iteration,
            csi_state=csi_state,
        )

        if not loop_decision.allow:
            return None

        # ---- POLICY ARBITRATION
        policy = self.policy.evaluate(
            csi_state=csi_state,
            iteration=iteration,
            context={"retry_count": retry_count},
        )

        if policy.decision == PolicyDecision.DENY:
            return None

        # ---- COORDINATED EVALUATION
        result = self.coordinator.run_cycle(
            iteration=iteration,
            csi_state=csi_state,
            expected_outcome=expected_outcome,
            actual_result=actual_result,
            retry_count=retry_count,
            last_error=last_error,
        )

        # ---- FEATURE FLAG: EMISSION GATE (NO MUTATION)
        if not self.flags.allow_action_proposals:
            return AutonomyCycleResult(
                loop=result.loop,
                self_check=result.self_check,
                recovery=result.recovery,
                proposal=None,
            )

        return result
