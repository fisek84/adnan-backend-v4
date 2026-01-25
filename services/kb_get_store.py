from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

from services.kb_file_store import FileKBStore
from services.kb_notion_store import KBNotionStore
from services.kb_store import KBStore

logger = logging.getLogger(__name__)


_FALLBACK_WARNED = False

_FILE_STORE: Optional[FileKBStore] = None
_NOTION_STORE: Optional[KBNotionStore] = None
_FALLBACK_STORE: Optional[KBStore] = None
_TEST_STUB_STORE: Optional[KBStore] = None


class _TestStubKBStore(KBStore):
    """Local-only KB store for smoke verification (no network).

    Enabled via env: KB_TEST_STUB=1
    - Returns deterministic total_entries=46
    - Flips meta.cache_hit False -> True on the second *request*
      (router builds grounding_pack twice per request).
    """

    def __init__(self) -> None:
        self._search_calls = 0
        self._last_meta: Dict[str, Any] = {
            "source": "notion",
            "mode": "notion",
            "cache_hit": False,
            "ttl_s": 60,
            "fetched_at": 123.0,
            "last_fetch_iso": None,
            "total_entries": 46,
            "hit_count": 0,
            "hits": 0,
        }

    async def get_entries(self, ctx: Optional[Dict[str, Any]] = None):
        return [{"id": f"E{i}", "title": f"T{i}", "content": "x"} for i in range(46)]

    async def search(self, query: str, *, top_k: int = 8, force: bool = False):
        self._search_calls += 1
        cache_hit = self._search_calls > 2
        meta = dict(self._last_meta)
        meta["cache_hit"] = cache_hit
        self._last_meta = dict(meta)
        return {"entries": [], "used_entry_ids": [], "meta": meta}

    def get_meta(self) -> Dict[str, Any]:
        return dict(self._last_meta)


def _env_kb_source() -> str:
    raw = os.getenv("KB_SOURCE")
    if isinstance(raw, str) and raw.strip():
        src = raw.strip().lower()
        return src if src in {"file", "notion"} else "file"

    # Defaulting contract:
    # - If KB_SOURCE is unset and NOTION_KB_DB_ID exists -> notion
    # - else -> file
    return "notion" if (os.getenv("NOTION_KB_DB_ID") or "").strip() else "file"


class _ErrorKBStore(KBStore):
    def __init__(self, *, error_code: str, error: str) -> None:
        self._meta: Dict[str, Any] = {
            "source": "notion",
            "mode": "notion",
            "cache_hit": False,
            "last_sync": None,
            "kb_error": error_code,
            "error": error,
            "ttl_s": 0,
            "fetched_at": 0.0,
            "last_fetch_iso": None,
            "total_entries": 0,
            "hit_count": 0,
            "hash": None,
        }

    async def get_entries(self, ctx: Optional[Dict[str, Any]] = None):
        return []

    async def load_all(self, *, force: bool = False):
        return {"entries": [], "meta": dict(self._meta)}

    async def search(self, query: str, *, top_k: int = 8, force: bool = False):
        meta = dict(self._meta)
        meta["hit_count"] = 0
        return {"entries": [], "used_entry_ids": [], "meta": meta}

    def get_meta(self) -> Dict[str, Any]:
        return dict(self._meta)


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

    async def load_all(self, *, force: bool = False):
        # Prefer Notion when available; fall back to file.
        try:
            if hasattr(self._notion, "load_all"):
                out = await self._notion.load_all(force=force)  # type: ignore[attr-defined]
                if isinstance(out, dict):
                    self._last_meta = dict(out.get("meta") or self._notion.get_meta())
                return out
        except Exception:
            pass

        # File store fallback (best-effort search semantics).
        if hasattr(self._file, "load_all"):
            return await self._file.load_all(force=force)  # type: ignore[attr-defined]
        entries = await self._file.get_entries(None)
        meta = self._file.get_meta()
        return {"entries": entries, "meta": meta}

    async def search(self, query: str, *, top_k: int = 8, force: bool = False):
        try:
            if hasattr(self._notion, "search"):
                out = await self._notion.search(query, top_k=top_k, force=force)  # type: ignore[attr-defined]
                if isinstance(out, dict):
                    self._last_meta = dict(out.get("meta") or self._notion.get_meta())
                return out
        except Exception:
            pass

        if hasattr(self._file, "search"):
            return await self._file.search(query, top_k=top_k, force=force)  # type: ignore[attr-defined]
        return {"entries": [], "used_entry_ids": [], "meta": self._file.get_meta()}

    def get_meta(self) -> Dict[str, Any]:
        return dict(self._last_meta)


def get_kb_store() -> KBStore:
    """Return a process-local KB store based on KB_SOURCE.

    Default is file (backward-compatible).
    """

    global _FILE_STORE, _NOTION_STORE, _FALLBACK_STORE, _TEST_STUB_STORE

    stub = (os.getenv("KB_TEST_STUB") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if stub:
        if _TEST_STUB_STORE is None:
            _TEST_STUB_STORE = _TestStubKBStore()
        return _TEST_STUB_STORE

    src = _env_kb_source()

    if _FILE_STORE is None:
        _FILE_STORE = FileKBStore()

    if src == "file":
        return _FILE_STORE

    # No silent empty: if notion selected but env is missing, return an error store
    # that can be surfaced in trace as kb_error.
    if not (os.getenv("NOTION_KB_DB_ID") or "").strip():
        return _ErrorKBStore(
            error_code="missing_NOTION_KB_DB_ID",
            error="NOTION_KB_DB_ID is required when KB_SOURCE=notion",
        )

    if _NOTION_STORE is None:
        _NOTION_STORE = KBNotionStore()

    if _FALLBACK_STORE is None:
        _FALLBACK_STORE = _FallbackKBStore(notion=_NOTION_STORE, file=_FILE_STORE)

    return _FALLBACK_STORE
