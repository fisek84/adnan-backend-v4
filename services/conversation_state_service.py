# C:\adnan-backend-v4\services\conversation_state_service.py

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum
from datetime import datetime


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
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


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
    """
    Canonical Conversation State (Conversation State Intelligence)

    RULES:
    - DATA ONLY (no decisions, no execution)
    - Runtime CSI snapshot
    - Persisted only to support continuity, not reasoning
    """

    state: str = CSIState.IDLE.value
    expected_input: str = "free"
    sop_list: List[Dict[str, Any]] = None
    active_sop_id: Optional[str] = None
    pending_decision: Optional[Dict[str, Any]] = None
    ts: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        if d.get("sop_list") is None:
            d["sop_list"] = []
        return d

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ConversationState":
        raw_state = data.get("state", CSIState.IDLE.value)

        if raw_state not in {s.value for s in CSIState}:
            raw_state = CSIState.IDLE.value

        return ConversationState(
            state=raw_state,
            expected_input=data.get("expected_input", "free"),
            sop_list=data.get("sop_list") or [],
            active_sop_id=data.get("active_sop_id"),
            pending_decision=data.get("pending_decision"),
            ts=float(data.get("ts") or 0.0),
        )


# ============================================================
# SERVICE
# ============================================================

class ConversationStateService:
    """
    ConversationStateService

    - Persists CSI snapshot
    - Emits CSI audit events
    - No business logic
    - No decisions
    - No execution
    """

    def __init__(self):
        BASE_PATH.mkdir(parents=True, exist_ok=True)
        self._state: ConversationState = self._load()

    # -------------------------
    # IO
    # -------------------------
    def _load(self) -> ConversationState:
        if not STATE_FILE.exists():
            s = ConversationState(ts=time.time(), sop_list=[])
            self._save_state(s, reason="init")
            return s

        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ConversationState.from_dict(data)
        except Exception:
            s = ConversationState(ts=time.time(), sop_list=[])
            self._save_state(s, reason="load_error")
            return s

    def _audit(self, previous: ConversationState, current: ConversationState, reason: str):
        try:
            event = {
                "ts": datetime.utcnow().isoformat(),
                "previous_state": previous.state,
                "next_state": current.state,
                "reason": reason,
                "snapshot": current.to_dict(),
            }
            with open(AUDIT_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")
        except Exception:
            pass  # audit must never break CSI

    def _save_state(self, s: ConversationState, reason: str):
        previous = self._state
        s.ts = time.time()
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(s.to_dict(), f, indent=2, ensure_ascii=False)
        self._state = s
        self._audit(previous, s, reason)

    # -------------------------
    # Public API
    # -------------------------
    def get(self) -> Dict[str, Any]:
        return self._state.to_dict()

    def reset(self) -> Dict[str, Any]:
        new_state = ConversationState(ts=time.time(), sop_list=[])
        self._save_state(new_state, reason="reset")
        return self.get()

    # -------------------------
    # SOP FLOW
    # -------------------------
    def set_sop_list(self, sops: List[Dict[str, Any]]) -> Dict[str, Any]:
        s = self._state
        s.state = CSIState.SOP_LIST.value
        s.expected_input = "sop_selection"
        s.sop_list = sops or []
        s.active_sop_id = None
        self._save_state(s, reason="set_sop_list")
        return self.get()

    def set_active_sop(self, sop_id: str) -> Dict[str, Any]:
        s = self._state
        s.state = CSIState.SOP_ACTIVE.value
        s.expected_input = "sop_query"
        s.active_sop_id = sop_id
        self._save_state(s, reason="set_active_sop")
        return self.get()

    def clear_sop_context(self) -> Dict[str, Any]:
        s = self._state
        s.sop_list = []
        s.active_sop_id = None
        if s.state in {
            CSIState.SOP_LIST.value,
            CSIState.SOP_ACTIVE.value,
        }:
            s.state = CSIState.IDLE.value
            s.expected_input = "free"
        self._save_state(s, reason="clear_sop_context")
        return self.get()

    # -------------------------
    # DECISION FLOW
    # -------------------------
    def set_pending_decision(self, text: str, fingerprint: str) -> Dict[str, Any]:
        s = self._state
        s.state = CSIState.DECISION_PENDING.value
        s.expected_input = "confirmation"
        s.pending_decision = {
            "text": text,
            "fingerprint": fingerprint,
            "created_ts": time.time(),
        }
        self._save_state(s, reason="set_pending_decision")
        return self.get()

    def clear_pending_decision(self) -> Dict[str, Any]:
        s = self._state
        s.pending_decision = None
        if s.state == CSIState.DECISION_PENDING.value:
            s.state = CSIState.IDLE.value
            s.expected_input = "free"
        self._save_state(s, reason="clear_pending_decision")
        return self.get()

    # -------------------------
    # EXECUTION
    # -------------------------
    def set_executing(self) -> Dict[str, Any]:
        s = self._state
        s.state = CSIState.EXECUTING.value
        s.expected_input = "none"
        self._save_state(s, reason="set_executing")
        return self.get()

    def set_idle(self) -> Dict[str, Any]:
        s = self._state
        s.state = CSIState.IDLE.value
        s.expected_input = "free"
        self._save_state(s, reason="set_idle")
        return self.get()
