from services.conversation_state_service import CSIState, ALLOWED_TRANSITIONS


class CSIStateMachine:
    """
    CSIStateMachine — HARD VALIDATION WRAPPER

    ROLE:
    - Validate CSI transitions against the SINGLE source of truth
    - No state ownership
    - No normalization
    - No new states
    """

    def is_valid(self, state: CSIState) -> bool:
        """
        Valid if state is a member of canonical CSIState enum.
        """
        return isinstance(state, CSIState)

    def can_transition(self, from_state: CSIState, to_state: CSIState) -> bool:
        """
        Hard validation using canonical ALLOWED_TRANSITIONS.
        """
        if not isinstance(from_state, CSIState):
            return False
        if not isinstance(to_state, CSIState):
            return False

        return to_state.value in ALLOWED_TRANSITIONS.get(from_state.value, set())
