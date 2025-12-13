# C:\adnan-backend-v4\services\csi_state_machine.py

from typing import Dict, Set
from services.conversation_state_service import CSIState


class CSIStateMachine:
    """
    Canonical CSI State Machine

    RULES:
    - Explicit transitions only
    - No execution
    - No decisions
    """

    def __init__(self):
        self._transitions: Dict[CSIState, Set[CSIState]] = {
            CSIState.IDLE: {
                CSIState.SOP_LIST,
                CSIState.SOP_ACTIVE,
            },

            CSIState.SOP_LIST: {
                CSIState.SOP_ACTIVE,
                CSIState.IDLE,
            },

            CSIState.SOP_ACTIVE: {
                CSIState.DECISION_PENDING,
                CSIState.IDLE,
            },

            CSIState.DECISION_PENDING: {
                CSIState.EXECUTING,
                CSIState.CANCELLED,
                CSIState.IDLE,
            },

            CSIState.EXECUTING: {
                CSIState.COMPLETED,
                CSIState.FAILED,
            },

            CSIState.COMPLETED: {
                CSIState.IDLE,
            },

            CSIState.CANCELLED: {
                CSIState.IDLE,
            },

            CSIState.FAILED: {
                CSIState.IDLE,
            },
        }

    # --------------------------------------------------
    # VALIDATION
    # --------------------------------------------------
    def is_transition_allowed(self, current: str, next_state: str) -> bool:
        try:
            cur = CSIState(current)
            nxt = CSIState(next_state)
        except Exception:
            return False

        return nxt in self._transitions.get(cur, set())

    def assert_transition(self, current: str, next_state: str):
        if not self.is_transition_allowed(current, next_state):
            raise ValueError(
                f"Illegal CSI transition: {current} → {next_state}"
            )
