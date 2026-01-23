from __future__ import annotations

import asyncio
import os
import random
import time
import threading
import concurrent.futures
from typing import Any, Dict, List, Optional, Tuple

import httpx

from services.kb_store import KBStore
from services.kb_types import KBEntry


class KBNotionReadFail(RuntimeError):
    """Raised when Notion KB read fails and no file fallback is applied."""

    error_code = "KB_NOTION_READ_FAIL"


# Process-local cache + singleflight (read-only)
_CACHE: Dict[str, Any] = {
    "entries": None,
    "fetched_at": 0.0,
    "last_sync": None,
}
_IN_FLIGHT: Optional[concurrent.futures.Future] = None
_CACHE_LOCK = threading.Lock()


def _env_int(name: str, default: int) -> int:
    v = (os.getenv(name) or "").strip()
    if not v:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _get_notion_token() -> Optional[str]:
    for k in ("NOTION_TOKEN", "NOTION_API_KEY"):
        v = (os.getenv(k) or "").strip()
        if v:
            return v
    return None


def _rt_concat(rt: Any) -> str:
    if not isinstance(rt, list):
        return ""
    parts: List[str] = []
    for node in rt:
        if not isinstance(node, dict):
            continue
        txt = node.get("plain_text")
        if isinstance(txt, str) and txt:
            parts.append(txt)
    return "\n".join(parts).strip()


def map_notion_page_to_kb_entry(page: Dict[str, Any]) -> Optional[KBEntry]:
    props = page.get("properties")
    if not isinstance(props, dict):
        return None

    status = props.get("Status")
    if isinstance(status, dict):
        sel = status.get("select")
        if isinstance(sel, dict):
            name = sel.get("name")
            if isinstance(name, str) and name.strip().lower() != "active":
                return None

    title_prop = props.get("Name")
    title = ""
    if isinstance(title_prop, dict):
        title = _rt_concat(title_prop.get("title"))

    id_prop = props.get("ID")
    kb_id = ""
    if isinstance(id_prop, dict):
        kb_id = _rt_concat(id_prop.get("rich_text"))
    if not kb_id:
        return None

    tags_prop = props.get("Tags")
    tags: List[str] = []
    if isinstance(tags_prop, dict):
        ms = tags_prop.get("multi_select")
        if isinstance(ms, list):
            for x in ms:
                if isinstance(x, dict) and isinstance(x.get("name"), str):
                    tags.append(x["name"])

    applies_prop = props.get("AppliesTo")
    applies_to: List[str] = []
    if isinstance(applies_prop, dict):
        ms = applies_prop.get("multi_select")
        if isinstance(ms, list):
            for x in ms:
                if isinstance(x, dict) and isinstance(x.get("name"), str):
                    applies_to.append(x["name"])
    if not applies_to:
        applies_to = ["all"]

    pr_prop = props.get("Priority")
    priority = 0.5
    if isinstance(pr_prop, dict):
        num = pr_prop.get("number")
        if isinstance(num, (int, float)):
            priority = float(num)

    content_prop = props.get("Content")
    content = ""
    if isinstance(content_prop, dict):
        content = _rt_concat(content_prop.get("rich_text"))
    if not content:
        return None

    updated_at_prop = props.get("UpdatedAt")
    updated_at: Optional[str] = None
    if isinstance(updated_at_prop, dict):
        date = updated_at_prop.get("date")
        if isinstance(date, dict) and isinstance(date.get("start"), str):
            updated_at = date.get("start")
    if not updated_at:
        le = page.get("last_edited_time")
        updated_at = le if isinstance(le, str) and le.strip() else None

    return {
        "id": kb_id,
        "title": title,
        "tags": tags,
        "applies_to": applies_to,
        "priority": priority,
        "content": content,
        "updated_at": updated_at,
    }


class NotionKBStore(KBStore):
    def __init__(
        self,
        *,
        db_id: Optional[str] = None,
        base_url: Optional[str] = None,
        notion_version: Optional[str] = None,
        cache_ttl_seconds: Optional[int] = None,
        timeout_seconds: float = 8.0,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._db_id = (db_id or os.getenv("NOTION_KB_DB_ID") or "").strip()
        self._base_url = (base_url or os.getenv("NOTION_API_BASE_URL") or "https://api.notion.com").strip()
        self._notion_version = (
            notion_version or os.getenv("NOTION_VERSION") or "2022-06-28"
        ).strip()
        self._ttl = cache_ttl_seconds if cache_ttl_seconds is not None else _env_int(
            "KB_NOTION_CACHE_TTL_SECONDS", 900
        )
        self._timeout = timeout_seconds
        self._transport = transport
        self._last_meta: Dict[str, Any] = {
            "source": "notion",
            "cache_hit": False,
            "last_sync": None,
        }

    def _headers(self) -> Dict[str, str]:
        token = _get_notion_token()
        if not token:
            raise KBNotionReadFail("Missing NOTION_TOKEN/NOTION_API_KEY")
        return {
            "Authorization": f"Bearer {token}",
            "Notion-Version": self._notion_version,
            "Content-Type": "application/json",
        }

    async def _query_pages(self) -> List[Dict[str, Any]]:
        if not self._db_id:
            raise KBNotionReadFail("Missing NOTION_KB_DB_ID")

        pages: List[Dict[str, Any]] = []
        next_cursor: Optional[str] = None

        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers(),
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            while True:
                body: Dict[str, Any] = {}
                if next_cursor:
                    body["start_cursor"] = next_cursor

                r = await client.post(f"/v1/databases/{self._db_id}/query", json=body)
                r.raise_for_status()
                data = r.json()
                results = data.get("results")
                if isinstance(results, list):
                    for x in results:
                        if isinstance(x, dict):
                            pages.append(x)

                has_more = bool(data.get("has_more"))
                next_cursor = data.get("next_cursor")
                if not has_more or not isinstance(next_cursor, str) or not next_cursor:
                    break

        return pages

    async def _fetch_entries_once(self) -> Tuple[List[KBEntry], Optional[str]]:
        pages = await self._query_pages()

        entries: List[KBEntry] = []
        last_sync: Optional[str] = None
        for p in pages:
            e = map_notion_page_to_kb_entry(p)
            if e is None:
                continue
            entries.append(e)
            ua = e.get("updated_at")
            if isinstance(ua, str) and ua.strip():
                if last_sync is None or ua > last_sync:
                    last_sync = ua

        return entries, last_sync

    async def _fetch_entries_with_retry(self) -> Tuple[List[KBEntry], Optional[str]]:
        backoffs = [0.2, 0.6]
        last_exc: Optional[BaseException] = None
        for attempt in range(2):
            try:
                return await self._fetch_entries_once()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                if attempt >= 1:
                    break
                await asyncio.sleep(backoffs[attempt] + random.random() * 0.05)
        raise KBNotionReadFail(str(last_exc) if last_exc else "Notion read failed")

    async def get_entries(self, ctx: Optional[Dict[str, Any]] = None) -> List[KBEntry]:
        global _IN_FLIGHT

        now = time.time()
        ttl = max(int(self._ttl), 0)

        do_fetch = False
        with _CACHE_LOCK:
            cached_entries = _CACHE.get("entries")
            fetched_at = float(_CACHE.get("fetched_at") or 0.0)
            last_sync = _CACHE.get("last_sync")
            if (
                isinstance(cached_entries, list)
                and cached_entries
                and ttl > 0
                and now - fetched_at < ttl
            ):
                self._last_meta = {
                    "source": "notion",
                    "cache_hit": True,
                    "last_sync": last_sync if isinstance(last_sync, str) else None,
                }
                return cached_entries

            if _IN_FLIGHT is not None and not _IN_FLIGHT.done():
                fut = _IN_FLIGHT
            else:
                fut = concurrent.futures.Future()
                _IN_FLIGHT = fut
                do_fetch = True

        if not do_fetch:
            try:
                entries, ls = await asyncio.wrap_future(fut)
                self._last_meta = {
                    "source": "notion",
                    "cache_hit": False,
                    "last_sync": ls,
                }
                return entries
            except Exception as exc:  # noqa: BLE001
                raise KBNotionReadFail(str(exc))

        try:
            entries, ls = await self._fetch_entries_with_retry()
            with _CACHE_LOCK:
                _CACHE["entries"] = entries
                _CACHE["fetched_at"] = time.time()
                _CACHE["last_sync"] = ls
                _IN_FLIGHT = None
                fut.set_result((entries, ls))
            self._last_meta = {
                "source": "notion",
                "cache_hit": False,
                "last_sync": ls,
            }
            return entries
        except Exception as exc:  # noqa: BLE001
            with _CACHE_LOCK:
                _IN_FLIGHT = None
                try:
                    fut.set_exception(exc)
                except Exception:
                    pass
            raise KBNotionReadFail(str(exc))

    def get_meta(self) -> Dict[str, Any]:
        return dict(self._last_meta)


def _reset_cache_for_tests() -> None:
    """Test hook. Not part of runtime contract."""
    global _IN_FLIGHT
    with _CACHE_LOCK:
        _CACHE["entries"] = None
        _CACHE["fetched_at"] = 0.0
        _CACHE["last_sync"] = None
        _IN_FLIGHT = None
