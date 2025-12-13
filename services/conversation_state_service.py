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


# ============================================================
# ALLOWED STATE TRANSITIONS (V1.0 LOCK)
# ============================================================

ALLOWED_TRANSITIONS = {
    CSIState.IDLE.value: {
        CSIState.SOP_LIST.value,
        CSIState.DECISION_PENDING.value,
        CSIState.EXECUTING.value,
    },
    CSIState.SOP_LIST.value: {
        CSIState.SOP_ACTIVE.value,
        CSIState.IDLE.value,
    },
    CSIState.SOP_ACTIVE.value: {
        CSIState.EXECUTING.value,
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
    },
    CSIState.FAILED.value: {
        CSIState.IDLE.value,
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
    request_id: Optional[str] = None
    execution_id: Optional[str] = None
    last_update_reason: Optional[str] = None
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d.get("sop_list") is None:
            d["sop_list"] = []
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
            request_id=data.get("request_id"),
            execution_id=data.get("execution_id"),
            last_update_reason=data.get("last_update_reason"),
            ts=float(data.get("ts") or 0.0),
        )


# ============================================================
# SERVICE
# ============================================================

class ConversationStateService:
    """
    CSI — V1.0 FINAL STATE AUTHORITY
    """

    LOCKED = True  # V1.0 FINAL LOCK

    def __init__(self):
        BASE_PATH.mkdir(parents=True, exist_ok=True)
        self._state: ConversationState = self._load()

    # -------------------------
    # IO
    # -------------------------
    def _load(self) -> ConversationState:
        if not STATE_FILE.exists():
            s = ConversationState(ts=time.time(), sop_list=[])
            self._persist(s, "init")
            return s

        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return ConversationState.from_dict(json.load(f))
        except Exception:
            s = ConversationState(ts=time.time(), sop_list=[])
            self._persist(s, "load_error")
            return s

    def _audit(
        self,
        prev: ConversationState,
        curr: ConversationState,
        reason: str,
        illegal: bool = False,
    ):
        try:
            with open(AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "timestamp": time.time(),
                    "from": prev.state,
                    "to": curr.state,
                    "reason": reason,
                    "illegal": illegal,
                    "request_id": curr.request_id,
                    "execution_id": curr.execution_id,
                }) + "\n")
        except Exception:
            pass

    def _persist(self, s: ConversationState, reason: str, illegal: bool = False):
        prev_snapshot = copy.deepcopy(self._state)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(s.to_dict(), f, indent=2, ensure_ascii=False)
        self._state = s
        self._audit(prev_snapshot, s, reason, illegal=illegal)

    # -------------------------
    # CORE TRANSITION GUARD
    # -------------------------
    def _transition(
        self,
        new_state: str,
        *,
        reason: str,
        request_id: Optional[str],
        execution_id: Optional[str] = None,
    ):
        current = self._state.state

        if self.LOCKED and new_state not in ALLOWED_TRANSITIONS.get(current, set()):
            logger.error(
                "ILLEGAL CSI TRANSITION: %s → %s | reason=%s",
                current,
                new_state,
                reason,
            )
            self._persist(
                self._state,
                reason=f"illegal_transition:{reason}",
                illegal=True,
            )
            return

        self._state.state = new_state
        self._state.request_id = request_id
        self._state.execution_id = execution_id
        self._state.last_update_reason = reason
        self._state.ts = time.time()
        self._persist(self._state, reason)

    # -------------------------
    # PUBLIC API
    # -------------------------
    def get(self) -> Dict[str, Any]:
        return self._state.to_dict()

    def set_executing(
        self,
        request_id: Optional[str] = None,
        execution_id: Optional[str] = None,
    ):
        self._transition(
            CSIState.EXECUTING.value,
            reason="set_executing",
            request_id=request_id,
            execution_id=execution_id,
        )
        return self.get()

    def set_idle(self, request_id: Optional[str] = None):
        self._transition(
            CSIState.IDLE.value,
            reason="set_idle",
            request_id=request_id,
        )
        return self.get()
