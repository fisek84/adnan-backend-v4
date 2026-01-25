from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List


_DEFAULT_MAX_TURNS = 10
_DEFAULT_MAX_SUMMARY_CHARS = 1500
_DEFAULT_MAX_TURN_CHARS = 600

_LOCK = threading.Lock()


def _now_unix() -> float:
    return time.time()


def _sha256_prefix(text: str, *, limit: int = 1000) -> str:
    s = (text or "")[: max(0, int(limit))]
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _truncate(text: str, *, max_chars: int) -> str:
    t = text or ""
    if max_chars <= 0:
        return "[TRUNCATED]"
    if len(t) <= max_chars:
        return t
    keep = max(0, max_chars - len("[TRUNCATED]"))
    return t[:keep] + "[TRUNCATED]"


def _state_path() -> str:
    p = (os.getenv("CEO_CONVERSATION_STATE_PATH") or "").strip()
    if p:
        return p
    return os.path.join(os.getcwd(), "_ceo_conversation_state.json")


def _load_db() -> Dict[str, Any]:
    path = _state_path()
    try:
        if not os.path.exists(path):
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_db(db: Dict[str, Any]) -> None:
    path = _state_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass

    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, path)
    except Exception:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            pass


@dataclass(frozen=True)
class ConversationStateSummary:
    conversation_id: str
    turns_used: int
    summary_text: str
    summary_len: int
    conversation_id_hash: str


class ConversationStateStore:
    """Minimal persisted multi-turn store (bounded).

    Designed for CEO Responses mode instruction injection.
    Content must never be logged verbatim by callers.
    """

    @staticmethod
    def get_summary(
        *,
        conversation_id: str,
        max_turns: int = _DEFAULT_MAX_TURNS,
        max_summary_chars: int = _DEFAULT_MAX_SUMMARY_CHARS,
    ) -> ConversationStateSummary:
        cid = (conversation_id or "").strip()
        if not cid:
            return ConversationStateSummary(
                conversation_id="",
                turns_used=0,
                summary_text="",
                summary_len=0,
                conversation_id_hash=_sha256_prefix(""),
            )

        with _LOCK:
            db = _load_db()
            st = db.get(cid)
            st = st if isinstance(st, dict) else {}
            turns = st.get("turns")
            turns = turns if isinstance(turns, list) else []

        # keep last N pairs (user+assistant) => store uses list of dicts
        # We interpret one "turn" as a pair (user, assistant) in storage.
        pairs: List[Dict[str, Any]] = [t for t in turns if isinstance(t, dict)]
        if max_turns <= 0:
            pairs = []
        else:
            pairs = pairs[-int(max_turns) :]

        lines: List[str] = []
        for i, it in enumerate(pairs, 1):
            u = it.get("user")
            a = it.get("assistant")
            u = u if isinstance(u, str) else ""
            a = a if isinstance(a, str) else ""
            if not (u.strip() or a.strip()):
                continue
            lines.append(f"{i}) USER: {_truncate(u.strip(), max_chars=400)}")
            lines.append(f"   ASSISTANT: {_truncate(a.strip(), max_chars=600)}")

        txt = "\n".join(lines).strip()
        txt = _truncate(txt, max_chars=int(max_summary_chars))

        return ConversationStateSummary(
            conversation_id=cid,
            turns_used=len(pairs),
            summary_text=txt,
            summary_len=len(txt),
            conversation_id_hash=_sha256_prefix(cid),
        )

    @staticmethod
    def append_turn(
        *,
        conversation_id: str,
        user_text: str,
        assistant_text: str,
        max_turns: int = _DEFAULT_MAX_TURNS,
        max_turn_chars: int = _DEFAULT_MAX_TURN_CHARS,
    ) -> None:
        cid = (conversation_id or "").strip()
        if not cid:
            return

        u = _truncate((user_text or "").strip(), max_chars=int(max_turn_chars))
        a = _truncate((assistant_text or "").strip(), max_chars=int(max_turn_chars))

        with _LOCK:
            db = _load_db()
            st = db.get(cid)
            st = st if isinstance(st, dict) else {}
            turns = st.get("turns")
            turns = turns if isinstance(turns, list) else []

            turns.append(
                {
                    "t": _now_unix(),
                    "user": u,
                    "assistant": a,
                }
            )

            if isinstance(max_turns, int) and max_turns > 0:
                turns = turns[-max_turns:]
            else:
                turns = []

            st["turns"] = turns
            st["updated_at"] = _now_unix()
            db[cid] = st
            _save_db(db)
