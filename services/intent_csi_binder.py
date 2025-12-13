# services/intent_csi_binder.py

from typing import Optional

from services.intent_contract import Intent, IntentType
from services.conversation_state_service import CSIState, ALLOWED_TRANSITIONS


# ============================================================
# BINDER RESULT (DATA ONLY)
# ============================================================

class BinderResult:
    def __init__(self, next_state: str, action: Optional[str] = None):
        self.next_state = next_state
        self.action = action  # signal only, NO execution


# ============================================================
# INTENT → CSI STATE BINDER
# ============================================================

class IntentCSIBinder:
    """
    Deterministic CSI binder.

    RULES:
    - No execution
    - No decisions
    - State transitions validated by CSI rules
    """

    def bind(self, intent: Intent, current_state: str) -> BinderResult:
        try:
            state = CSIState(current_state)
        except Exception:
            return BinderResult(next_state=CSIState.IDLE.value)

        # ----------------------------------------------------
        # GLOBAL RESET
        # ----------------------------------------------------
        if intent.type == IntentType.RESET:
            return BinderResult(
                next_state=CSIState.IDLE.value,
                action="reset",
            )

        desired_state = state.value
        action: Optional[str] = None

        # ----------------------------------------------------
        # IDLE
        # ----------------------------------------------------
        if state == CSIState.IDLE:
            if intent.type == IntentType.LIST_SOPS:
                desired_state = CSIState.SOP_LIST.value
                action = "list_sops"

            elif intent.type == IntentType.CREATE:
                desired_state = CSIState.DECISION_PENDING.value
                action = "create"

        # ----------------------------------------------------
        # SOP LIST
        # ----------------------------------------------------
        elif state == CSIState.SOP_LIST:
            if intent.type == IntentType.VIEW_SOP:
                desired_state = CSIState.SOP_ACTIVE.value
                action = "select_sop"

            elif intent.type == IntentType.CANCEL:
                desired_state = CSIState.IDLE.value

        # ----------------------------------------------------
        # SOP ACTIVE
        # ----------------------------------------------------
        elif state == CSIState.SOP_ACTIVE:
            if intent.type == IntentType.REQUEST_EXECUTION:
                desired_state = CSIState.DECISION_PENDING.value
                action = "request_execution"

            elif intent.type == IntentType.CANCEL:
                desired_state = CSIState.IDLE.value

        # ----------------------------------------------------
        # DECISION PENDING (CRITICAL FIX)
        # ----------------------------------------------------
        elif state == CSIState.DECISION_PENDING:
            if intent.type == IntentType.CONFIRM:
                desired_state = CSIState.EXECUTING.value
                action = "confirm_execution"

            elif intent.type == IntentType.CANCEL:
                desired_state = CSIState.IDLE.value
                action = "cancel_execution"

            else:
                # IGNORE everything else (CREATE, LIST, etc.)
                return BinderResult(
                    next_state=CSIState.DECISION_PENDING.value,
                    action=None,
                )

        # ----------------------------------------------------
        # EXECUTING (LOCKED)
        # ----------------------------------------------------
        elif state == CSIState.EXECUTING:
            desired_state = CSIState.EXECUTING.value

        # ----------------------------------------------------
        # VALIDATION (KANONSKA)
        # ----------------------------------------------------
        allowed = ALLOWED_TRANSITIONS.get(state.value, set())
        if desired_state not in allowed:
            return BinderResult(next_state=state.value)

        return BinderResult(
            next_state=desired_state,
            action=action,
        )
