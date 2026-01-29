from __future__ import annotations

import os
import hashlib
import json
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

    @staticmethod
    def _stable_json_dumps(obj: Any) -> str:
        try:
            return json.dumps(
                obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
        except Exception:
            return json.dumps(str(obj), ensure_ascii=False)

    @classmethod
    def _sha256_hex(cls, obj: Any) -> str:
        data = cls._stable_json_dumps(obj).encode("utf-8")
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _make_snippet(content: str, *, max_len: int = 280) -> str:
        t = (content or "").strip()
        if not t:
            return ""
        if len(t) <= max_len:
            return t
        return t[: max_len - 1].rstrip() + "…"

    async def load_all(self, *, force: bool = False) -> Dict[str, Any]:
        _, entries = self.load_payload_and_entries()
        # File store is not TTL-cached (by design).
        meta: Dict[str, Any] = {
            "mode": "file",
            "source": "file",
            "cache_hit": False,
            "last_sync": None,
            "ttl_s": 0,
            "fetched_at": 0.0,
            "last_fetch_iso": None,
            "total_entries": len(entries),
            "hash": self._sha256_hex(entries),
        }
        self._last_meta = {"source": "file", "cache_hit": False, "last_sync": None}
        return {"entries": entries, "meta": meta}

    async def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        force: bool = False,
        intent: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = self.load_payload()
        # Use the exact same scoring/selection logic as the legacy grounding pack.
        # This preserves determinism and keeps existing tests stable.
        try:
            from services.grounding_pack_service import GroundingPackService  # noqa: PLC0415

            baseline = GroundingPackService._retrieve_kb(
                prompt=query, kb=payload, intent=intent
            )
            selected = list(baseline.selected_entries)
            used_ids = list(baseline.used_entry_ids)
        except Exception:
            selected = []
            used_ids = []

        top_k_i = int(top_k) if int(top_k) > 0 else 8
        if len(selected) > top_k_i:
            selected = selected[:top_k_i]
            used_ids = used_ids[:top_k_i]

        meta: Dict[str, Any] = {
            "mode": "file",
            "source": "file",
            "cache_hit": False,
            "last_sync": None,
            "ttl_s": 0,
            "fetched_at": 0.0,
            "last_fetch_iso": None,
            "total_entries": len(payload.get("entries") or [])
            if isinstance(payload, dict)
            else 0,
            "hash": self._sha256_hex(
                payload.get("entries") if isinstance(payload, dict) else []
            ),
            "hit_count": len(selected),
        }
        self._last_meta = {"source": "file", "cache_hit": False, "last_sync": None}
        return {"entries": selected, "used_entry_ids": used_ids, "meta": meta}
