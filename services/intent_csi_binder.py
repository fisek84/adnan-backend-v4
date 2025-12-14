from typing import Optional
from services.intent_contract import Intent, IntentType
from services.conversation_state_service import CSIState, ALLOWED_TRANSITIONS


class BinderResult:
    def __init__(
        self,
        next_state: str,
        action: Optional[str] = None,
        payload: Optional[dict] = None,
    ):
        self.next_state = next_state
        self.action = action
        self.payload = payload or {}


class IntentCSIBinder:
    """
    Deterministic CSI binder — FINAL / LOCKED

    PRINCIPLES:
    - CSI state has priority over intent
    - GENERIC CONFIRM / CANCEL are resolved by context
    - No execution logic
    - No side effects
    """

    def bind(self, intent: Intent, current_state: str) -> BinderResult:
        try:
            state = CSIState(current_state)
        except Exception:
            state = CSIState.IDLE

        # ------------------------------------------------
        # RESET (HIGHEST PRIORITY)
        # ------------------------------------------------
        if intent.type == IntentType.RESET:
            return BinderResult(
                next_state=CSIState.IDLE.value,
                action="reset",
            )

        # ------------------------------------------------
        # EXECUTING (HARD LOCK)
        # ------------------------------------------------
        if state == CSIState.EXECUTING:
            return BinderResult(
                next_state=CSIState.EXECUTING.value,
                action=None,
            )

        desired_state = state.value
        action: Optional[str] = None
        payload = intent.payload or {}

        # ------------------------------------------------
        # IDLE
        # ------------------------------------------------
        if state == CSIState.IDLE:
            if intent.type == IntentType.GOAL_CREATE:
                desired_state = CSIState.GOAL_DRAFT.value
                action = "create_goal"

            elif intent.type == IntentType.TASK_CREATE:
                desired_state = CSIState.TASK_DRAFT.value
                action = "create_task"

            else:
                return BinderResult(
                    next_state=CSIState.IDLE.value,
                    action="chat",
                )

        # ------------------------------------------------
        # GOAL DRAFT (FAZA 3) — FINAL FIX
        # ------------------------------------------------
        elif state == CSIState.GOAL_DRAFT:
            if intent.type in (IntentType.CONFIRM, IntentType.GOAL_CONFIRM):
                desired_state = CSIState.IDLE.value
                action = "confirm_goal"

            elif intent.type in (IntentType.CANCEL, IntentType.GOAL_CANCEL):
                desired_state = CSIState.IDLE.value
                action = "cancel_goal"

            elif intent.type == IntentType.PLAN_CREATE:
                desired_state = CSIState.PLAN_DRAFT.value
                action = "create_plan"

        # ------------------------------------------------
        # PLAN DRAFT (FAZA 4)
        # ------------------------------------------------
        elif state == CSIState.PLAN_DRAFT:
            if intent.type in (IntentType.CONFIRM, IntentType.PLAN_CONFIRM):
                desired_state = CSIState.IDLE.value
                action = "confirm_plan"

            elif intent.type in (IntentType.CANCEL, IntentType.PLAN_CANCEL):
                desired_state = CSIState.IDLE.value
                action = "cancel_plan"

            elif intent.type == IntentType.TASK_GENERATE_FROM_PLAN:
                desired_state = CSIState.PLAN_DRAFT.value
                action = "generate_tasks_from_plan"

        # ------------------------------------------------
        # VALIDATION (FINAL GUARD)
        # ------------------------------------------------
        allowed = ALLOWED_TRANSITIONS.get(state.value, set())
        if desired_state not in allowed:
            return BinderResult(
                next_state=state.value,
                action=None,
            )

        return BinderResult(
            next_state=desired_state,
            action=action,
            payload=payload,
        )
