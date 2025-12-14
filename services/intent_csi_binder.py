from typing import Optional

from services.intent_contract import Intent, IntentType
from services.conversation_state_service import CSIState, ALLOWED_TRANSITIONS


# ============================================================
# BINDER RESULT (DATA ONLY)
# ============================================================

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


# ============================================================
# INTENT → CSI STATE BINDER (KANONSKI, LOCKED)
# ============================================================

class IntentCSIBinder:
    """
    Deterministic CSI binder — FINAL.

    RULES:
    - CSI state has absolute priority
    - Intent is already normalized
    - NO execution
    - NO decisions
    - RESET always wins
    - EXECUTING is fully locked
    """

    def bind(self, intent: Intent, current_state: str) -> BinderResult:
        try:
            state = CSIState(current_state)
        except Exception:
            state = CSIState.IDLE

        # ----------------------------------------------------
        # GLOBAL RESET (HIGHEST PRIORITY)
        # ----------------------------------------------------
        if intent.type == IntentType.RESET:
            return BinderResult(
                next_state=CSIState.IDLE.value,
                action="reset",
            )

        # ----------------------------------------------------
        # EXECUTING (HARD LOCK)
        # ----------------------------------------------------
        if state == CSIState.EXECUTING:
            return BinderResult(
                next_state=CSIState.EXECUTING.value,
                action=None,
            )

        desired_state = state.value
        action: Optional[str] = None
        payload: dict = {}

        # ----------------------------------------------------
        # IDLE
        # ----------------------------------------------------
        if state == CSIState.IDLE:
            if intent.type == IntentType.LIST_SOPS:
                desired_state = CSIState.SOP_LIST.value
                action = "list_sops"

            elif intent.type == IntentType.GOAL_CREATE:
                desired_state = CSIState.GOAL_DRAFT.value
                action = "create_goal"
                payload = intent.payload or {}

            elif intent.type == IntentType.TASK_CREATE:
                desired_state = CSIState.TASK_DRAFT.value
                action = "create_task"
                payload = intent.payload or {}

            else:
                # fallback chat — ostajemo u IDLE
                return BinderResult(
                    next_state=CSIState.IDLE.value,
                    action="chat",
                )

        # ----------------------------------------------------
        # GOAL DRAFT (FAZA 3)
        # ----------------------------------------------------
        elif state == CSIState.GOAL_DRAFT:
            if intent.type == IntentType.GOAL_CONFIRM:
                desired_state = CSIState.IDLE.value
                action = "confirm_goal"

            elif intent.type == IntentType.GOAL_CANCEL:
                desired_state = CSIState.IDLE.value
                action = "cancel_goal"

            elif intent.type == IntentType.PLAN_CREATE:
                desired_state = CSIState.PLAN_DRAFT.value
                action = "create_plan"
                payload = intent.payload or {}

        # ----------------------------------------------------
        # PLAN DRAFT (FAZA 4)
        # ----------------------------------------------------
        elif state == CSIState.PLAN_DRAFT:
            if intent.type == IntentType.PLAN_CONFIRM:
                desired_state = CSIState.IDLE.value
                action = "confirm_plan"

            elif intent.type == IntentType.PLAN_CANCEL:
                desired_state = CSIState.IDLE.value
                action = "cancel_plan"

            elif intent.type == IntentType.TASK_GENERATE_FROM_PLAN:
                desired_state = CSIState.PLAN_DRAFT.value
                action = "generate_tasks_from_plan"

        # ----------------------------------------------------
        # TASK DRAFT (FAZA 3)
        # ----------------------------------------------------
        elif state == CSIState.TASK_DRAFT:
            if intent.type == IntentType.TASK_CONFIRM:
                desired_state = CSIState.IDLE.value
                action = "confirm_task"

            elif intent.type == IntentType.TASK_CANCEL:
                desired_state = CSIState.IDLE.value
                action = "cancel_task"

        # ----------------------------------------------------
        # SOP LIST
        # ----------------------------------------------------
        elif state == CSIState.SOP_LIST:
            if intent.type == IntentType.VIEW_SOP:
                desired_state = CSIState.SOP_ACTIVE.value
                action = "select_sop"
                payload = intent.payload or {}

            elif intent.type == IntentType.CANCEL:
                desired_state = CSIState.IDLE.value
                action = "cancel"

        # ----------------------------------------------------
        # SOP ACTIVE
        # ----------------------------------------------------
        elif state == CSIState.SOP_ACTIVE:
            if intent.type == IntentType.REQUEST_EXECUTION:
                desired_state = CSIState.DECISION_PENDING.value
                action = "request_execution"

            elif intent.type == IntentType.CANCEL:
                desired_state = CSIState.IDLE.value
                action = "cancel"

        # ----------------------------------------------------
        # DECISION PENDING
        # ----------------------------------------------------
        elif state == CSIState.DECISION_PENDING:
            if intent.type == IntentType.CONFIRM:
                desired_state = CSIState.EXECUTING.value
                action = "confirm_execution"

            elif intent.type == IntentType.CANCEL:
                desired_state = CSIState.IDLE.value
                action = "cancel_execution"

            else:
                return BinderResult(
                    next_state=CSIState.DECISION_PENDING.value,
                    action=None,
                )

        # ----------------------------------------------------
        # VALIDATION (FINAL GUARD)
        # ----------------------------------------------------
        allowed = ALLOWED_TRANSITIONS.get(state.value, set())
        if desired_state not in allowed:
            return BinderResult(next_state=state.value)

        return BinderResult(
            next_state=desired_state,
            action=action,
            payload=payload,
        )
