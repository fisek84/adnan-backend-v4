from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum
from datetime import datetime
import copy
import logging

logger = logging.getLogger(__name__)

# ============================================================
# CSI STATE ENUM (KANONSKI)
# ============================================================

class CSIState(Enum):
    IDLE = "IDLE"
    SOP_LIST = "SOP_LIST"
    SOP_ACTIVE = "SOP_ACTIVE"
    DECISION_PENDING = "DECISION_PENDING"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

    # ================================
    # GOALS (FAZA 3)
    # ================================
    GOAL_DRAFT = "GOAL_DRAFT"

    # ================================
    # TASKS (FAZA 3)
    # ================================
    TASK_DRAFT = "TASK_DRAFT"

    # ================================
    # PROJECTS (FAZA 3)
    # ================================
    PROJECT_DRAFT = "PROJECT_DRAFT"

    # ================================
    # PLANS (FAZA 4)
    # ================================
    PLAN_DRAFT = "PLAN_DRAFT"

    # ================================
    # AUTONOMY (FAZA 5)  ✅ NOVO
    # ================================
    AUTONOMOUS_LOOP = "AUTONOMOUS_LOOP"


# ============================================================
# ALLOWED STATE TRANSITIONS (FINAL LOCK)
# ============================================================

ALLOWED_TRANSITIONS = {
    CSIState.IDLE.value: {
        CSIState.SOP_LIST.value,
        CSIState.GOAL_DRAFT.value,
        CSIState.TASK_DRAFT.value,
        CSIState.PROJECT_DRAFT.value,
        CSIState.PLAN_DRAFT.value,
        CSIState.AUTONOMOUS_LOOP.value,   # ✅
    },
    CSIState.SOP_LIST.value: {
        CSIState.SOP_ACTIVE.value,
        CSIState.IDLE.value,
    },
    CSIState.SOP_ACTIVE.value: {
        CSIState.DECISION_PENDING.value,
        CSIState.IDLE.value,
    },
    CSIState.DECISION_PENDING.value: {
        CSIState.EXECUTING.value,
        CSIState.IDLE.value,
    },
    CSIState.EXECUTING.value: {
        CSIState.COMPLETED.value,
        CSIState.FAILED.value,
    },
    CSIState.COMPLETED.value: {
        CSIState.IDLE.value,
        CSIState.AUTONOMOUS_LOOP.value,   # ✅ self-check loop
    },
    CSIState.FAILED.value: {
        CSIState.IDLE.value,
        CSIState.AUTONOMOUS_LOOP.value,   # ✅ recovery loop
    },
    CSIState.GOAL_DRAFT.value: {
        CSIState.IDLE.value,
    },
    CSIState.TASK_DRAFT.value: {
        CSIState.IDLE.value,
    },
    CSIState.PROJECT_DRAFT.value: {
        CSIState.IDLE.value,
    },
    CSIState.PLAN_DRAFT.value: {
        CSIState.IDLE.value,
    },
    CSIState.AUTONOMOUS_LOOP.value: {
        CSIState.IDLE.value,
        CSIState.EXECUTING.value,
        CSIState.FAILED.value,
        CSIState.COMPLETED.value,
    },
}

# ============================================================
# STORAGE
# ============================================================

BASE_PATH = Path(__file__).resolve().parent.parent / "adnan_ai" / "memory"
STATE_FILE = BASE_PATH / "conversation_state.json"
AUDIT_FILE = BASE_PATH / "csi_audit.log"


# ============================================================
# DATA MODEL
# ============================================================

@dataclass
class ConversationState:
    state: str = CSIState.IDLE.value
    expected_input: str = "free"
    sop_list: List[Dict[str, Any]] = None
    active_sop_id: Optional[str] = None
    pending_decision: Optional[Dict[str, Any]] = None

    goal_draft: Optional[Dict[str, Any]] = None
    task_draft: Optional[Dict[str, Any]] = None
    project_draft: Optional[Dict[str, Any]] = None
    plan_draft: Optional[Dict[str, Any]] = None

    request_id: Optional[str] = None
    last_update_reason: Optional[str] = None
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["sop_list"] = d.get("sop_list") or []
        return d

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ConversationState":
        state = data.get("state", CSIState.IDLE.value)
        if state not in ALLOWED_TRANSITIONS:
            state = CSIState.IDLE.value

        return ConversationState(
            state=state,
            expected_input=data.get("expected_input", "free"),
            sop_list=data.get("sop_list") or [],
            active_sop_id=data.get("active_sop_id"),
            pending_decision=data.get("pending_decision"),
            goal_draft=data.get("goal_draft"),
            task_draft=data.get("task_draft"),
            project_draft=data.get("project_draft"),
            plan_draft=data.get("plan_draft"),
            request_id=data.get("request_id"),
            last_update_reason=data.get("last_update_reason"),
            ts=float(data.get("ts") or 0.0),
        )


# ============================================================
# SERVICE
# ============================================================

class ConversationStateService:
    """
    CSI — FINAL STATE AUTHORITY (HARD LOCK)
    """

    LOCKED = True

    def __init__(self):
        BASE_PATH.mkdir(parents=True, exist_ok=True)
        self._state: ConversationState = self._load()

    def _load(self) -> ConversationState:
        if not STATE_FILE.exists():
            s = ConversationState(ts=time.time(), sop_list=[])
            self._persist(s, reason="init", bootstrap=True)
            return s

        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return ConversationState.from_dict(json.load(f))
        except Exception:
            s = ConversationState(ts=time.time(), sop_list=[])
            self._persist(s, reason="load_error", bootstrap=True)
            return s

    def _audit(self, prev, curr, reason, illegal=False):
        try:
            with open(AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": datetime.utcnow().isoformat(),
                    "from": prev.state if prev else None,
                    "to": curr.state,
                    "reason": reason,
                    "illegal": illegal,
                    "request_id": curr.request_id,
                }) + "\n")
        except Exception:
            pass

    def _persist(self, s, *, reason, illegal=False, bootstrap=False):
        prev = None if bootstrap else copy.deepcopy(self._state)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(s.to_dict(), f, indent=2, ensure_ascii=False)
        self._state = s
        self._audit(prev, s, reason, illegal)

    def _transition(self, new_state, *, reason, request_id):
        current = self._state.state
        if self.LOCKED and new_state not in ALLOWED_TRANSITIONS.get(current, set()):
            self._persist(self._state, reason=f"illegal_transition:{reason}", illegal=True)
            return

        self._state.state = new_state
        self._state.request_id = request_id
        self._state.last_update_reason = reason
        self._state.ts = time.time()
        self._persist(self._state, reason=reason)

    def get(self):
        return self._state.to_dict()

    def _clear_context(self):
        self._state.sop_list = []
        self._state.active_sop_id = None
        self._state.pending_decision = None
        self._state.goal_draft = None
        self._state.task_draft = None
        self._state.project_draft = None
        self._state.plan_draft = None
        self._state.expected_input = "free"

    def set_idle(self, request_id=None):
        self._clear_context()
        self._transition(CSIState.IDLE.value, reason="set_idle", request_id=request_id)
        return self.get()

    def set_plan_draft(self, *, plan: Dict[str, Any], request_id=None):
        self._transition(CSIState.PLAN_DRAFT.value, reason="set_plan_draft", request_id=request_id)
        self._state.plan_draft = plan
        self._state.expected_input = "plan_confirmation"
        self._persist(self._state, reason="plan_draft_set")
        return self.get()
