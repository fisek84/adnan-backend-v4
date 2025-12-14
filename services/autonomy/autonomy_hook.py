# services/autonomy/autonomy_hook.py

from typing import Optional, Dict, Any

from services.autonomy.autonomy_entrypoint import AutonomyEntryPoint
from services.autonomy.kill_switch import AutonomyKillSwitch
from services.autonomy.feature_flags import AutonomyFeatureFlags
from services.autonomy.safe_mode import AutonomySafeMode
from services.conversation_state_service import ConversationStateService


class AutonomyHook:
    """
    Thin integration layer between Orchestrator and Autonomy.

    RULES:
    - Read-only
    - No CSI mutation
    - No execution
    - No policy ownership
    """

    def __init__(
        self,
        conversation_state: ConversationStateService,
        *,
        kill_switch: AutonomyKillSwitch,
        feature_flags: AutonomyFeatureFlags,
        safe_mode: AutonomySafeMode,
    ):
        self.entrypoint = AutonomyEntryPoint(
            conversation_state=conversation_state,
            kill_switch=kill_switch,
            feature_flags=feature_flags,
            safe_mode=safe_mode,
        )

    def evaluate(
        self,
        *,
        iteration: int,
        expected_outcome: Optional[Dict[str, Any]] = None,
        actual_result: Optional[Dict[str, Any]] = None,
        retry_count: int = 0,
        last_error: Optional[str] = None,
    ):
        """
        Executes ONE autonomy evaluation cycle.
        """
        return self.entrypoint.run(
            iteration=iteration,
            expected_outcome=expected_outcome,
            actual_result=actual_result,
            retry_count=retry_count,
            last_error=last_error,
        )
