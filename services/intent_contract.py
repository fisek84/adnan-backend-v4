from enum import Enum
from dataclasses import dataclass
from typing import Optional, Dict, Any


# ============================================================
# INTENT ENUM (KANONSKI SET)
# ============================================================

class IntentType(Enum):
    NONE = "none"                            # small talk / irrelevant
    LIST_SOPS = "list_sops"                  # "pokaži sop-ove"
    VIEW_SOP = "view_sop"                    # "onaj drugi"
    REQUEST_EXECUTION = "request_execution"  # "pokreni ovo"

    CREATE = "create"                        # generic create (fallback)

    # ================================
    # GOALS (FAZA 3)
    # ================================
    GOAL_CREATE = "goal_create"
    GOAL_CONFIRM = "goal_confirm"
    GOAL_CANCEL = "goal_cancel"

    # ================================
    # TASKS (FAZA 3)
    # ================================
    TASK_CREATE = "task_create"
    TASK_CONFIRM = "task_confirm"
    TASK_CANCEL = "task_cancel"

    # ================================
    # PLANS (FAZA 4)
    # ================================
    PLAN_CREATE = "plan_create"
    PLAN_CONFIRM = "plan_confirm"
    PLAN_CANCEL = "plan_cancel"

    # ================================
    # TASK GENERATION (FAZA 4)  ✅ NOVO
    # ================================
    TASK_GENERATE_FROM_PLAN = "task_generate_from_plan"

    ASK_CLARIFICATION = "ask_clarification"
    RESET = "reset"


# ============================================================
# INTENT PAYLOAD
# ============================================================

@dataclass
class Intent:
    """
    Intent is a SIGNAL, not a decision.
    """
    type: IntentType
    confidence: float                      # 0.0 – 1.0
    payload: Optional[Dict[str, Any]] = None
