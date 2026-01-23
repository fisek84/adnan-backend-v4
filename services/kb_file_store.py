from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from services.identity_loader import load_json_file, resolve_path
from services.kb_store import KBStore
from services.kb_types import KBEntry


class FileKBStore(KBStore):
    """Loads KB entries from the existing JSON file format.

    Compatibility notes:
    - Uses the exact same path resolution as current grounding pack:
      `IDENTITY_KNOWLEDGE_PATH` (if set) else `resolve_path("knowledge.json")`.
    - Does not reorder entries.
    """

    def __init__(self) -> None:
        self._last_meta: Dict[str, Any] = {
            "source": "file",
            "cache_hit": False,
            "last_sync": None,
        }

    def _resolve_kb_path(self) -> str:
        kb_path = (os.getenv("IDENTITY_KNOWLEDGE_PATH") or "").strip()
        if kb_path:
            return os.path.abspath(kb_path)
        return resolve_path("knowledge.json")

    def load_payload(self) -> Dict[str, Any]:
        try:
            payload = load_json_file(self._resolve_kb_path())
            return payload if isinstance(payload, dict) else {}
        except Exception as exc:  # noqa: BLE001
            return {
                "version": "unknown",
                "description": "kb_load_failed",
                "entries": [],
                "_error": str(exc),
            }

    def load_payload_and_entries(self) -> tuple[Dict[str, Any], List[KBEntry]]:
        payload = self.load_payload()
        return payload, self._parse_entries(payload)

    @staticmethod
    def _coerce_str_list(v: Any) -> List[str]:
        if not isinstance(v, list):
            return []
        out: List[str] = []
        for x in v:
            if isinstance(x, str):
                out.append(x)
        return out

    @classmethod
    def _parse_entry(cls, raw: Any) -> Optional[KBEntry]:
        if not isinstance(raw, dict):
            return None

        _id = raw.get("id")
        content = raw.get("content")
        if not isinstance(_id, str) or not _id:
            return None
        if not isinstance(content, str) or not content:
            return None

        title = raw.get("title")
        tags = cls._coerce_str_list(raw.get("tags"))
        applies_to = cls._coerce_str_list(raw.get("applies_to"))
        if not applies_to:
            applies_to = ["all"]

        pr = raw.get("priority")
        try:
            priority = float(pr)
        except Exception:
            priority = 0.5

        updated_at = raw.get("updated_at")
        if not isinstance(updated_at, str) or not updated_at.strip():
            updated_at = None

        return {
            "id": _id,
            "title": title if isinstance(title, str) else "",
            "tags": tags,
            "applies_to": applies_to,
            "priority": priority,
            "content": content,
            "updated_at": updated_at,
        }

    def _parse_entries(self, payload: Dict[str, Any]) -> List[KBEntry]:
        entries_raw = payload.get("entries")
        items = entries_raw if isinstance(entries_raw, list) else []

        out: List[KBEntry] = []
        for e in items:
            parsed = self._parse_entry(e)
            if parsed is not None:
                out.append(parsed)
        return out

    async def get_entries(self, ctx: Optional[Dict[str, Any]] = None) -> List[KBEntry]:
        _, entries = self.load_payload_and_entries()
        self._last_meta = {
            "source": "file",
            "cache_hit": False,
            "last_sync": None,
        }
        return entries

    def get_meta(self) -> Dict[str, Any]:
        return dict(self._last_meta)
