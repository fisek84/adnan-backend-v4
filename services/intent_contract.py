from enum import Enum
from typing import Optional, Dict, Any


class IntentType(Enum):
    # =====================================================
    # CORE
    # =====================================================
    CHAT = "chat"
    RESET = "reset"

    CONFIRM = "confirm"
    CANCEL = "cancel"

    # =====================================================
    # EXECUTION
    # =====================================================
    REQUEST_EXECUTION = "request_execution"

    # =====================================================
    # FAZA 3 — GOALS
    # =====================================================
    GOAL_CREATE = "goal_create"
    GOAL_CONFIRM = "goal_confirm"
    GOAL_CANCEL = "goal_cancel"
    GOALS_LIST = "goals_list"   # ← DODANO (READ-ONLY)

    # =====================================================
    # FAZA 4 — PLANS
    # =====================================================
    PLAN_CREATE = "plan_create"
    PLAN_CONFIRM = "plan_confirm"
    PLAN_CANCEL = "plan_cancel"

    TASK_GENERATE_FROM_PLAN = "task_generate_from_plan"

    # =====================================================
    # FAZA 5 — TASK LIFECYCLE (USER INTENTS)
    # =====================================================
    TASK_CREATE = "task_create"
    TASK_CONFIRM = "task_confirm"
    TASK_CANCEL = "task_cancel"

    TASK_START = "task_start"        # user says: "pokreni zadatak"
    TASK_COMPLETE = "task_complete"  # user says: "zadatak je gotov"
    TASK_FAIL = "task_fail"          # user says: "zadatak nije uspio"

    # =====================================================
    # SOP
    # =====================================================
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
