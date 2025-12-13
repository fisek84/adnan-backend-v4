# C:\adnan-backend-v4\services\intent_csi_binder.py

from typing import Optional
from services.intent_contract import Intent, IntentType
from services.conversation_state_service import CSIState
from services.csi_state_machine import CSIStateMachine


# ============================================================
# BINDER RESULT (DATA ONLY)
# ============================================================

class BinderResult:
    def __init__(self, next_state: str, action: Optional[str] = None):
        self.next_state = next_state
        self.action = action  # signal only, no execution


# ============================================================
# INTENT → CSI STATE BINDER
# ============================================================

class IntentCSIBinder:
    """
    Deterministic mapping:
    (IntentType + CSIState) → next CSIState

    RULES:
    - No execution
    - No decision making
    - No heuristics
    - State transitions MUST be allowed by CSIStateMachine
    """

    def __init__(self):
        self._sm = CSIStateMachine()

    def bind(self, intent: Intent, current_state: str) -> BinderResult:
        try:
            state = CSIState(current_state)
        except Exception:
            # hard safety fallback
            return BinderResult(next_state=CSIState.IDLE.value)

        # ----------------------------------------------------
        # GLOBAL RESET (always allowed)
        # ----------------------------------------------------
        if intent.type == IntentType.RESET:
            return BinderResult(next_state=CSIState.IDLE.value)

        desired_state = state.value
        action: Optional[str] = None

        # ----------------------------------------------------
        # IDLE
        # ----------------------------------------------------
        if state == CSIState.IDLE:
            if intent.type == IntentType.LIST_SOPS:
                desired_state = CSIState.SOP_LIST.value
                action = "list_sops"

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
        # DECISION PENDING
        # ----------------------------------------------------
        elif state == CSIState.DECISION_PENDING:
            if intent.type == IntentType.CONFIRM:
                desired_state = CSIState.EXECUTING.value
                action = "confirm_execution"

            elif intent.type == IntentType.CANCEL:
                desired_state = CSIState.CANCELLED.value
                action = "cancel_execution"

        # ----------------------------------------------------
        # EXECUTING (no transitions allowed from intent)
        # ----------------------------------------------------
        elif state == CSIState.EXECUTING:
            desired_state = CSIState.EXECUTING.value

        # ----------------------------------------------------
        # VALIDATION VIA STATE MACHINE
        # ----------------------------------------------------
        if not self._sm.is_transition_allowed(
            current_state=state.value,
            next_state=desired_state,
        ):
            # illegal transition → ignore intent
            return BinderResult(next_state=state.value)

        return BinderResult(
            next_state=desired_state,
            action=action,
        )
