from __future__ import annotations

from typing import Any, Dict, Set

from services.snapshot_fields_allowlist import allowlist_for_db_key


MAX_TASK_TEXT_LEN = 1500


def _safe_str(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _normalize_field_value(v: Any) -> str:
    if v is None:
        return ""

    if isinstance(v, str):
        return v.strip()

    # Common snapshot encodings: date objects may be dict-ish.
    if isinstance(v, dict):
        for k in ("start", "date", "value"):
            val = v.get(k)
            if isinstance(val, str) and val.strip():
                return val.strip()
        return ""

    if isinstance(v, list):
        parts = [str(x).strip() for x in v if isinstance(x, (str, int, float))]
        parts = [p for p in parts if p]
        return ", ".join(parts)

    # Last resort: stable stringification.
    try:
        s = str(v).strip()
        return s
    except Exception:
        return ""


def _truncate(text: str, max_len: int = MAX_TASK_TEXT_LEN) -> str:
    if not isinstance(text, str):
        return ""
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    # Hard cap only (ASCII-safe, deterministic).
    return text[:max_len]


_ALLOWED_TASK_OUT_KEYS: Set[str] = set()


def _allowed_task_field_keys() -> Set[str]:
    global _ALLOWED_TASK_OUT_KEYS

    if _ALLOWED_TASK_OUT_KEYS:
        return set(_ALLOWED_TASK_OUT_KEYS)

    specs = allowlist_for_db_key("tasks")
    if specs:
        _ALLOWED_TASK_OUT_KEYS = {s.out_key for s in specs if getattr(s, "out_key", None)}

    # Defensive fallback (still consistent with snapshot allowlist contract).
    if not _ALLOWED_TASK_OUT_KEYS:
        _ALLOWED_TASK_OUT_KEYS = {"status", "due", "assigned_to"}

    return set(_ALLOWED_TASK_OUT_KEYS)


def build_agent_task_from_snapshot(task_item: Any) -> Dict[str, Any]:
    """Build deterministic delegated-agent input from a Notion snapshot task item.

    Input shape (from Notion snapshot contract):
      {
        "notion_id": "...",
        "title": "...",
        "url": "...",
        "fields": {...}
      }

    Output:
      {
        "task_text": "...",
        "source_task": {"notion_id": "...", "url": "..."}
      }

    Rules:
    - Pure helper, no side effects
    - Uses only allowlisted snapshot fields
    - Never performs Notion writes
    - task_text is capped to MAX_TASK_TEXT_LEN
    """

    item = task_item if isinstance(task_item, dict) else {}

    notion_id = _safe_str(item.get("notion_id") or item.get("id"))
    title = _safe_str(item.get("title") or item.get("name"))
    url = _safe_str(item.get("url"))

    fields = item.get("fields") if isinstance(item.get("fields"), dict) else {}

    allowed = _allowed_task_field_keys()

    def _get_field(out_key: str) -> str:
        if out_key not in allowed:
            return "unknown"
        val = _normalize_field_value(fields.get(out_key))
        return val if val else "unknown"

    status = _get_field("status")
    due_date = _get_field("due")
    owner = _get_field("assigned_to")

    task_text = (
        f"Task: {title or 'unknown'}\n\n"
        f"Source: {url or 'unknown'}\n\n"
        "Details:\n"
        f"- status: {status}\n"
        f"- due: {due_date}\n"
        f"- owner: {owner}"
    )

    return {
        "task_text": _truncate(task_text),
        "source_task": {
            "notion_id": notion_id,
            "url": url,
        },
    }
