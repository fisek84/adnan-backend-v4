# services/conversation_state_service.py

from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


BASE_PATH = Path(__file__).resolve().parent.parent / "adnan_ai" / "memory"
STATE_FILE = BASE_PATH / "conversation_state.json"


@dataclass
class ConversationState:
    """
    Canonical Conversation State (Conversation State Intelligence)

    RULES:
    - This is DATA only (no decisions, no execution).
    - Single source of truth for the current conversation phase.
    """

    state: str = "IDLE"  # IDLE | SOP_LIST | SOP_ACTIVE | DECISION_PENDING | EXECUTING
    expected_input: str = "free"  # free | sop_selection | sop_query | confirmation | none
    sop_list: List[Dict[str, Any]] = None  # last presented SOP list [{id,name,version}]
    active_sop_id: Optional[str] = None
    pending_decision: Optional[Dict[str, Any]] = None  # {text, fingerprint, created_ts}
    ts: float = 0.0  # last update

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # dataclass default None handling
        if d.get("sop_list") is None:
            d["sop_list"] = []
        return d

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "ConversationState":
        return ConversationState(
            state=data.get("state", "IDLE"),
            expected_input=data.get("expected_input", "free"),
            sop_list=data.get("sop_list") or [],
            active_sop_id=data.get("active_sop_id"),
            pending_decision=data.get("pending_decision"),
            ts=float(data.get("ts") or 0.0),
        )


class ConversationStateService:
    """
    ConversationStateService

    - persists state to adnan_ai/memory/conversation_state.json
    - provides safe getters/setters
    - no business logic, no execution
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
            self._save_state(s)
            return s

        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ConversationState.from_dict(data)
        except Exception:
            s = ConversationState(ts=time.time(), sop_list=[])
            self._save_state(s)
            return s

    def _save_state(self, s: ConversationState) -> None:
        s.ts = time.time()
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(s.to_dict(), f, indent=2, ensure_ascii=False)

    # -------------------------
    # Public API
    # -------------------------
    def get(self) -> Dict[str, Any]:
        return self._state.to_dict()

    def reset(self) -> Dict[str, Any]:
        self._state = ConversationState(ts=time.time(), sop_list=[])
        self._save_state(self._state)
        return self.get()

    # ---- SOP flow ----
    def set_sop_list(self, sops: List[Dict[str, Any]]) -> Dict[str, Any]:
        self._state.state = "SOP_LIST"
        self._state.expected_input = "sop_selection"
        self._state.sop_list = sops or []
        self._state.active_sop_id = None
        self._save_state(self._state)
        return self.get()

    def set_active_sop(self, sop_id: str) -> Dict[str, Any]:
        self._state.state = "SOP_ACTIVE"
        self._state.expected_input = "sop_query"
        self._state.active_sop_id = sop_id
        self._save_state(self._state)
        return self.get()

    def clear_sop_context(self) -> Dict[str, Any]:
        self._state.sop_list = []
        self._state.active_sop_id = None
        if self._state.state.startswith("SOP"):
            self._state.state = "IDLE"
            self._state.expected_input = "free"
        self._save_state(self._state)
        return self.get()

    # ---- Decision flow ----
    def set_pending_decision(self, text: str, fingerprint: str) -> Dict[str, Any]:
        self._state.state = "DECISION_PENDING"
        self._state.expected_input = "confirmation"
        self._state.pending_decision = {
            "text": text,
            "fingerprint": fingerprint,
            "created_ts": time.time(),
        }
        self._save_state(self._state)
        return self.get()

    def clear_pending_decision(self) -> Dict[str, Any]:
        self._state.pending_decision = None
        if self._state.state == "DECISION_PENDING":
            self._state.state = "IDLE"
            self._state.expected_input = "free"
        self._save_state(self._state)
        return self.get()

    def set_executing(self) -> Dict[str, Any]:
        self._state.state = "EXECUTING"
        self._state.expected_input = "none"
        self._save_state(self._state)
        return self.get()

    def set_idle(self) -> Dict[str, Any]:
        self._state.state = "IDLE"
        self._state.expected_input = "free"
        self._save_state(self._state)
        return self.get()
