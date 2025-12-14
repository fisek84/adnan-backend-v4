from enum import Enum
from typing import Optional, Dict, Any


class IntentType(Enum):
    # CORE
    CHAT = "chat"
    RESET = "reset"

    CONFIRM = "confirm"
    CANCEL = "cancel"

    # EXECUTION
    REQUEST_EXECUTION = "request_execution"

    # FAZA 3
    GOAL_CREATE = "goal_create"
    GOAL_CONFIRM = "goal_confirm"
    GOAL_CANCEL = "goal_cancel"

    TASK_CREATE = "task_create"
    TASK_CONFIRM = "task_confirm"
    TASK_CANCEL = "task_cancel"

    # FAZA 4
    PLAN_CREATE = "plan_create"
    PLAN_CONFIRM = "plan_confirm"
    PLAN_CANCEL = "plan_cancel"

    TASK_GENERATE_FROM_PLAN = "task_generate_from_plan"

    # SOP
    LIST_SOPS = "list_sops"
    VIEW_SOP = "view_sop"


class Intent:
    def __init__(
        self,
        type: IntentType,
        confidence: float,
        payload: Optional[Dict[str, Any]] = None,
    ):
        self.type = type
        self.confidence = confidence
        self.payload = payload or {}
