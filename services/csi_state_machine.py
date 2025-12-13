from services.conversation_state_service import CSIState

class CSIStateMachine:
    """
    CSIStateMachine — V1.0 COMPATIBILITY LAYER

    PURPOSE:
    - Provide backward compatibility for intent binding
    - Enforce V1.0 CSI contract
    - NO new states
    - NO soft states (CANCELLED REMOVED)
    """

    def __init__(self):
        # Allowed terminal / non-terminal states only
        self.valid_states = {
            CSIState.IDLE,
            CSIState.SOP_LIST,
            CSIState.SOP_ACTIVE,
            CSIState.DECISION_PENDING,
            CSIState.EXECUTING,
            CSIState.COMPLETED,
            CSIState.FAILED,
        }

    def is_valid(self, state: CSIState) -> bool:
        return state in self.valid_states

    def normalize(self, state: CSIState) -> CSIState:
        """
        Normalize any incoming state to V1.0 CSI.
        """
        if state in self.valid_states:
            return state
        return CSIState.IDLE
