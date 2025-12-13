from services.conversation_state_service import CSIState


class CSIStateMachine:
    """
    CSIStateMachine — V1.0 HARDENED CONTRACT

    PURPOSE:
    - Enforce legal CSI state transitions
    - Prevent illegal jumps (especially READ → EXECUTION)
    - Preserve V1.0 compatibility
    - NO new states
    """

    def __init__(self):
        # All allowed states (explicit)
        self.valid_states = {
            CSIState.IDLE,
            CSIState.SOP_LIST,
            CSIState.SOP_ACTIVE,
            CSIState.DECISION_PENDING,
            CSIState.EXECUTING,
            CSIState.COMPLETED,
            CSIState.FAILED,
        }

        # Explicit allowed transitions
        self.allowed_transitions = {
            CSIState.IDLE: {
                CSIState.SOP_LIST,
                CSIState.DECISION_PENDING,
            },
            CSIState.SOP_LIST: {
                CSIState.SOP_ACTIVE,
                CSIState.IDLE,
            },
            CSIState.SOP_ACTIVE: {
                CSIState.SOP_LIST,
                CSIState.IDLE,
            },
            CSIState.DECISION_PENDING: {
                CSIState.EXECUTING,
                CSIState.IDLE,
            },
            CSIState.EXECUTING: {
                CSIState.COMPLETED,
                CSIState.FAILED,
            },
            CSIState.COMPLETED: {
                CSIState.IDLE,
            },
            CSIState.FAILED: {
                CSIState.IDLE,
            },
        }

    def is_valid(self, state: CSIState) -> bool:
        return state in self.valid_states

    def can_transition(self, from_state: CSIState, to_state: CSIState) -> bool:
        """
        Hard validation of CSI transitions.
        """
        if from_state not in self.valid_states:
            return False
        if to_state not in self.valid_states:
            return False

        return to_state in self.allowed_transitions.get(from_state, set())

    def normalize(self, state: CSIState) -> CSIState:
        """
        Normalize external / unknown states safely.
        """
        if state in self.valid_states:
            return state
        return CSIState.IDLE
