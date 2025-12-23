from enum import Enum
from typing import Optional, Dict, Any, List


class IntentType(Enum):
    CHAT = "chat"
    RESET = "reset"
    CONFIRM = "confirm"
    CANCEL = "cancel"

    SYSTEM_QUERY = "system_query"
    REQUEST_EXECUTION = "request_execution"

    GOAL_CREATE = "goal_create"
    GOAL_CONFIRM = "goal_confirm"
    GOAL_CANCEL = "goal_cancel"
    GOALS_LIST = "goals_list"

    PLAN_CREATE = "plan_create"
    PLAN_CONFIRM = "plan_confirm"
    PLAN_CANCEL = "plan_cancel"

    TASK_GENERATE_FROM_PLAN = "task_generate_from_plan"
    TASK_CREATE = "task_create"
    TASK_CONFIRM = "task_confirm"
    TASK_CANCEL = "task_cancel"
    TASK_START = "task_start"
    TASK_COMPLETE = "task_complete"
    TASK_FAIL = "task_fail"

    LIST_SOPS = "list_sops"
    VIEW_SOP = "view_sop"


INTENT_DEFINITIONS: Dict[IntentType, Dict[str, Any]] = {
    # -------------------------
    # NON-EXECUTABLE / UX ONLY
    # -------------------------
    IntentType.CHAT: {
        "executable": False,
        "allowed_commands": [],
        "description": "Conversational input only",
    },
    IntentType.RESET: {
        "executable": False,
        "allowed_commands": [],
        "description": "Reset conversation or state (UX handled)",
    },
    IntentType.CONFIRM: {
        "executable": False,
        "allowed_commands": [],
        "description": "User confirmation",
    },
    IntentType.CANCEL: {
        "executable": False,
        "allowed_commands": [],
        "description": "User cancellation",
    },
    IntentType.REQUEST_EXECUTION: {
        "executable": False,
        "allowed_commands": [],
        "description": "Execution request wrapper (internal)",
    },
    # -------------------------
    # READ-ONLY (SAFE)
    # -------------------------
    IntentType.SYSTEM_QUERY: {
        "executable": True,
        "allowed_commands": ["system_query"],
        "description": "Read-only system state query",
    },
    IntentType.GOALS_LIST: {
        "executable": True,
        "allowed_commands": ["list_goals"],
        "description": "List goals (read-only)",
    },
    IntentType.LIST_SOPS: {
        "executable": True,
        "allowed_commands": ["list_sops"],
        "description": "List available SOPs (read-only)",
    },
    IntentType.VIEW_SOP: {
        "executable": True,
        "allowed_commands": ["view_sop"],
        "description": "View SOP content (read-only)",
    },
    # -------------------------
    # WRITE (GOVERNED)
    # -------------------------
    IntentType.GOAL_CREATE: {
        "executable": True,
        "allowed_commands": ["update_goal"],
        "description": "Create or update a goal",
    },
    IntentType.PLAN_CREATE: {
        "executable": True,
        "allowed_commands": ["create_plan"],
        "description": "Create a plan",
    },
    IntentType.TASK_GENERATE_FROM_PLAN: {
        "executable": True,
        "allowed_commands": ["generate_tasks"],
        "description": "Generate tasks from plan",
    },
    IntentType.TASK_CREATE: {
        "executable": True,
        "allowed_commands": ["create_task"],
        "description": "Create a task",
    },
    IntentType.TASK_START: {
        "executable": True,
        "allowed_commands": ["update_state"],
        "description": "Start a task",
    },
    IntentType.TASK_COMPLETE: {
        "executable": True,
        "allowed_commands": ["update_state"],
        "description": "Complete a task",
    },
    IntentType.TASK_FAIL: {
        "executable": True,
        "allowed_commands": ["update_state"],
        "description": "Mark task as failed",
    },
    # -------------------------
    # UX FLOW CONFIRMATIONS
    # -------------------------
    IntentType.GOAL_CONFIRM: {
        "executable": False,
        "allowed_commands": [],
        "description": "Confirm goal creation (UX flow)",
    },
    IntentType.GOAL_CANCEL: {
        "executable": False,
        "allowed_commands": [],
        "description": "Cancel goal creation (UX flow)",
    },
    IntentType.PLAN_CONFIRM: {
        "executable": False,
        "allowed_commands": [],
        "description": "Confirm plan (UX flow)",
    },
    IntentType.PLAN_CANCEL: {
        "executable": False,
        "allowed_commands": [],
        "description": "Cancel plan (UX flow)",
    },
    IntentType.TASK_CONFIRM: {
        "executable": False,
        "allowed_commands": [],
        "description": "Confirm task creation",
    },
    IntentType.TASK_CANCEL: {
        "executable": False,
        "allowed_commands": [],
        "description": "Cancel task creation",
    },
}


class Intent:
    def __init__(
        self,
        type: IntentType,
        confidence: float,
        payload: Optional[Dict[str, Any]] = None,
        source: Optional[str] = None,
    ):
        self.type = type
        self.confidence = confidence
        self.payload = payload or {}
        self.source = source

    @property
    def definition(self) -> Dict[str, Any]:
        return INTENT_DEFINITIONS.get(self.type, {})

    @property
    def is_executable(self) -> bool:
        return self.definition.get("executable", False)

    @property
    def allowed_commands(self) -> List[str]:
        return self.definition.get("allowed_commands", [])
