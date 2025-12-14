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

            elif intent.type == IntentType.PLAN_CREATE:
                desired_state = CSIState.PLAN_CREATE.value
                action = "create_plan"

            elif intent.type == IntentType.TASK_CREATE:
                desired_state = CSIState.TASK_CREATE.value
                action = "create_task"

            else:
                return BinderResult(
                    next_state=CSIState.IDLE.value,
                    action="chat",
                )

        # ------------------------------------------------
        # GOAL DRAFT (FAZA 3)
        # ------------------------------------------------
        elif state == CSIState.GOAL_DRAFT:
            if intent.type in (IntentType.CONFIRM, IntentType.GOAL_CONFIRM):
                desired_state = CSIState.IDLE.value
                action = "confirm_goal"

            elif intent.type in (IntentType.CANCEL, IntentType.GOAL_CANCEL):
                desired_state = CSIState.IDLE.value
                action = "cancel_goal"

            elif intent.type == IntentType.PLAN_CREATE:
                desired_state = CSIState.PLAN_CREATE.value
                action = "create_plan"

        # ------------------------------------------------
        # PLAN CREATE (FAZA 4)
        # ------------------------------------------------
        elif state == CSIState.PLAN_CREATE:
            if intent.type == IntentType.CONFIRM:
                desired_state = CSIState.PLAN_DRAFT.value
                action = "draft_plan"

            elif intent.type in (IntentType.CANCEL, IntentType.PLAN_CANCEL):
                desired_state = CSIState.IDLE.value
                action = "cancel_plan"

        # ------------------------------------------------
        # PLAN DRAFT (FAZA 4)
        # ------------------------------------------------
        elif state == CSIState.PLAN_DRAFT:
            if intent.type in (IntentType.CONFIRM, IntentType.PLAN_CONFIRM):
                desired_state = CSIState.PLAN_CONFIRM.value
                action = "confirm_plan"

            elif intent.type in (IntentType.CANCEL, IntentType.PLAN_CANCEL):
                desired_state = CSIState.IDLE.value
                action = "cancel_plan"

        # ------------------------------------------------
        # PLAN CONFIRM (FAZA 4)
        # ------------------------------------------------
        elif state == CSIState.PLAN_CONFIRM:
            desired_state = CSIState.IDLE.value
            action = None

        # ------------------------------------------------
        # TASK CREATE (FAZA 5)
        # ------------------------------------------------
        elif state == CSIState.TASK_CREATE:
            if intent.type == IntentType.CONFIRM:
                desired_state = CSIState.TASK_DRAFT.value
                action = "draft_task"

            elif intent.type in (IntentType.CANCEL, IntentType.TASK_CANCEL):
                desired_state = CSIState.IDLE.value
                action = "cancel_task"

        # ------------------------------------------------
        # TASK DRAFT (FAZA 5)
        # ------------------------------------------------
        elif state == CSIState.TASK_DRAFT:
            if intent.type in (IntentType.CONFIRM, IntentType.TASK_CONFIRM):
                desired_state = CSIState.TASK_CONFIRM.value
                action = "confirm_task"

            elif intent.type in (IntentType.CANCEL, IntentType.TASK_CANCEL):
                desired_state = CSIState.IDLE.value
                action = "cancel_task"

        # ------------------------------------------------
        # TASK CONFIRM (FAZA 5)
        # ------------------------------------------------
        elif state == CSIState.TASK_CONFIRM:
            if intent.type == IntentType.TASK_START:
                desired_state = CSIState.TASK_EXECUTING.value
                action = "start_task"

            elif intent.type in (IntentType.CANCEL, IntentType.TASK_CANCEL):
                desired_state = CSIState.IDLE.value
                action = "cancel_task"

        # ------------------------------------------------
        # TASK EXECUTING (FAZA 5)
        # ------------------------------------------------
        elif state == CSIState.TASK_EXECUTING:
            if intent.type == IntentType.TASK_COMPLETE:
                desired_state = CSIState.TASK_DONE.value
                action = "complete_task"

            elif intent.type == IntentType.TASK_FAIL:
                desired_state = CSIState.TASK_FAILED.value
                action = "fail_task"

        # ------------------------------------------------
        # TASK DONE / FAILED (FAZA 5)
        # ------------------------------------------------
        elif state in (CSIState.TASK_DONE, CSIState.TASK_FAILED):
            desired_state = CSIState.IDLE.value
            action = None

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
