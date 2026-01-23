from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from services.kb_file_store import FileKBStore
from services.kb_notion_store import KBNotionReadFail, NotionKBStore
from services.kb_store import KBStore

logger = logging.getLogger(__name__)


_FALLBACK_WARNED = False

_FILE_STORE: Optional[FileKBStore] = None
_NOTION_STORE: Optional[NotionKBStore] = None
_FALLBACK_STORE: Optional[KBStore] = None


def _env_kb_source() -> str:
    src = (os.getenv("KB_SOURCE") or "file").strip().lower()
    return src if src in {"file", "notion"} else "file"


class _FallbackKBStore(KBStore):
    def __init__(self, *, notion: KBStore, file: KBStore) -> None:
        self._notion = notion
        self._file = file
        self._last_meta: Dict[str, Any] = {
            "source": "notion",
            "cache_hit": False,
            "last_sync": None,
        }

    async def get_entries(self, ctx: Optional[Dict[str, Any]] = None):
        global _FALLBACK_WARNED
        try:
            entries = await self._notion.get_entries(ctx)
            meta = self._notion.get_meta()
            self._last_meta = {
                "source": "notion",
                "cache_hit": bool(meta.get("cache_hit")),
                "last_sync": meta.get("last_sync"),
            }
            return entries
        except Exception as exc:  # noqa: BLE001
            error_code = getattr(exc, "error_code", "KB_NOTION_READ_FAIL")
            if not _FALLBACK_WARNED:
                _FALLBACK_WARNED = True
                rid = None
                if isinstance(ctx, dict):
                    rid = ctx.get("request_id") or ctx.get("requestId")
                logger.warning(
                    "KB Notion read failed; falling back to file",
                    extra={
                        "kb_source": "notion",
                        "fallback_used": True,
                        "request_id": rid,
                        "error_code": error_code,
                    },
                )

            entries = await self._file.get_entries(ctx)
            meta = self._file.get_meta()
            self._last_meta = {
                "source": "file_fallback",
                "cache_hit": bool(meta.get("cache_hit")),
                "last_sync": meta.get("last_sync"),
                "error_code": error_code,
            }
            return entries

    def get_meta(self) -> Dict[str, Any]:
        return dict(self._last_meta)


def get_kb_store() -> KBStore:
    """Return a process-local KB store based on KB_SOURCE.

    Default is file (backward-compatible).
    """

    global _FILE_STORE, _NOTION_STORE, _FALLBACK_STORE

    src = _env_kb_source()

    if _FILE_STORE is None:
        _FILE_STORE = FileKBStore()

    if src == "file":
        return _FILE_STORE

    if _NOTION_STORE is None:
        _NOTION_STORE = NotionKBStore()

    if _FALLBACK_STORE is None:
        _FALLBACK_STORE = _FallbackKBStore(notion=_NOTION_STORE, file=_FILE_STORE)

    # Validate env only when requested.
    if not (os.getenv("NOTION_KB_DB_ID") or "").strip():
        raise KBNotionReadFail("NOTION_KB_DB_ID is required when KB_SOURCE=notion")

    return _FALLBACK_STORE
