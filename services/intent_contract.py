from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict


class IntentType(Enum):
    CHAT = "chat"

    RESET = "reset"

    GOAL_CREATE = "goal_create"
    GOAL_CONFIRM = "goal_confirm"
    GOAL_CANCEL = "goal_cancel"

    PLAN_CREATE = "plan_create"
    PLAN_CONFIRM = "plan_confirm"
    PLAN_CANCEL = "plan_cancel"

    TASK_CREATE = "task_create"
    TASK_CONFIRM = "task_confirm"
    TASK_CANCEL = "task_cancel"

    LIST_SOPS = "list_sops"
    VIEW_SOP = "view_sop"

    REQUEST_EXECUTION = "request_execution"
    CONFIRM = "confirm"
    CANCEL = "cancel"

    TASK_GENERATE_FROM_PLAN = "task_generate_from_plan"


@dataclass
class Intent:
    type: IntentType
    confidence: float = 1.0
    payload: Optional[Dict] = None
