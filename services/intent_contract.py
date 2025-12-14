from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any


class IntentType(Enum):
    # -------------------------------------------------
    # GENERIC
    # -------------------------------------------------
    CHAT = "chat"
    RESET = "reset"
    CONFIRM = "confirm"
    CANCEL = "cancel"

    # -------------------------------------------------
    # SOP
    # -------------------------------------------------
    LIST_SOPS = "list_sops"
    VIEW_SOP = "view_sop"
    REQUEST_EXECUTION = "request_execution"

    # -------------------------------------------------
    # GOALS (FAZA 3)
    # -------------------------------------------------
    GOAL_CREATE = "goal_create"
    GOAL_CONFIRM = "goal_confirm"
    GOAL_CANCEL = "goal_cancel"

    # -------------------------------------------------
    # TASKS (FAZA 3)
    # -------------------------------------------------
    TASK_CREATE = "task_create"
    TASK_CONFIRM = "task_confirm"
    TASK_CANCEL = "task_cancel"

    # -------------------------------------------------
    # PLANS (FAZA 4)
    # -------------------------------------------------
    PLAN_CREATE = "plan_create"
    PLAN_CONFIRM = "plan_confirm"
    PLAN_CANCEL = "plan_cancel"
    TASK_GENERATE_FROM_PLAN = "task_generate_from_plan"


@dataclass
class Intent:
    type: IntentType
    confidence: float = 1.0
    payload: Optional[Dict[str, Any]] = None
