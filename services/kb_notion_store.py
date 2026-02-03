from __future__ import annotations

import asyncio
import hashlib
import json
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


# Process-local cache + singleflight (read-only).
# NOTE: GroundingPackService can call KB methods from worker threads that create
# fresh event loops (asyncio.run). Therefore the cache/singleflight must be
# thread-based, not loop-based.
_CACHE_BY_DB: Dict[str, Dict[str, Any]] = {}
_IN_FLIGHT_BY_DB: Dict[str, concurrent.futures.Future] = {}
_CACHE_LOCK = threading.Lock()


def _env_int(name: str, default: int) -> int:
    v = (os.getenv(name) or "").strip()
    if not v:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _stable_json_dumps(obj: Any) -> str:
    try:
        return json.dumps(
            obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    except Exception:
        return json.dumps(str(obj), ensure_ascii=False)


def _sha256_hex(obj: Any) -> str:
    return hashlib.sha256(_stable_json_dumps(obj).encode("utf-8")).hexdigest()


def _utc_iso(ts: Optional[float] = None) -> str:
    t = time.time() if ts is None else float(ts)
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))


def _get_notion_token() -> Optional[str]:
    for k in ("NOTION_TOKEN", "NOTION_API_KEY"):
        v = (os.getenv(k) or "").strip()
        if v:
            return v
    return None


def _env_allowed_sources() -> Optional[set[str]]:
    """Optional allowlist for KB 'Source' property.

    If KB_ALLOWED_SOURCES is unset/empty -> allow all sources.
    If set -> only entries whose Source (case-insensitive) is in the allowlist pass.
    """

    raw = (os.getenv("KB_ALLOWED_SOURCES") or "").strip()
    if not raw:
        return None
    out: set[str] = set()
    for part in raw.split(","):
        p = part.strip().lower()
        if p:
            out.add(p)
    return out or None


def _extract_source(props: Dict[str, Any]) -> Optional[str]:
    src = props.get("Source")
    if not isinstance(src, dict):
        return None

    sel = src.get("select")
    if isinstance(sel, dict) and isinstance(sel.get("name"), str):
        return sel.get("name")

    ms = src.get("multi_select")
    if isinstance(ms, list) and ms:
        first = ms[0]
        if isinstance(first, dict) and isinstance(first.get("name"), str):
            return first.get("name")

    rt = src.get("rich_text")
    if isinstance(rt, list) and rt:
        return _rt_concat(rt)

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


def _extract_status_value(props: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
    """Return (status_prop_exists, status_name)."""

    status = props.get("Status")
    if not isinstance(status, dict):
        return False, None

    # Support both legacy `select` and Notion `status` property types.
    sel = status.get("select")
    st = status.get("status")

    name: Optional[str] = None
    if isinstance(sel, dict) and isinstance(sel.get("name"), str):
        name = sel.get("name")
    elif isinstance(st, dict) and isinstance(st.get("name"), str):
        name = st.get("name")

    return True, (name.strip() if isinstance(name, str) and name.strip() else None)


def _extract_rich_text_prop(props: Dict[str, Any], prop_name: str) -> str:
    p = props.get(prop_name)
    if not isinstance(p, dict):
        return ""

    # Notion rich_text property
    rt = p.get("rich_text")
    if isinstance(rt, list):
        return _rt_concat(rt)
    return ""


def _extract_title_prop(props: Dict[str, Any], prop_name: str) -> str:
    p = props.get(prop_name)
    if not isinstance(p, dict):
        return ""

    title = p.get("title")
    if isinstance(title, list):
        return _rt_concat(title)
    return ""


def _extract_multi_select(props: Dict[str, Any], prop_name: str) -> List[str]:
    p = props.get(prop_name)
    if not isinstance(p, dict):
        return []
    ms = p.get("multi_select")
    if not isinstance(ms, list):
        return []
    out: List[str] = []
    for x in ms:
        if isinstance(x, dict) and isinstance(x.get("name"), str) and x["name"].strip():
            out.append(x["name"].strip())
    return out


def _extract_date_start(props: Dict[str, Any], prop_name: str) -> Optional[str]:
    p = props.get(prop_name)
    if not isinstance(p, dict):
        return None
    date = p.get("date")
    if (
        isinstance(date, dict)
        and isinstance(date.get("start"), str)
        and date["start"].strip()
    ):
        return date["start"].strip()
    return None


def _extract_number(props: Dict[str, Any], prop_name: str) -> Optional[float]:
    p = props.get(prop_name)
    if not isinstance(p, dict):
        return None
    n = p.get("number")
    if n is None:
        return None
    try:
        return float(n)
    except Exception:
        return None


def _extract_kb_id(page: Dict[str, Any], props: Dict[str, Any]) -> Optional[str]:
    """Best-effort: prefer ID rich_text; else use Notion page id (no dashes)."""

    kb_id = _extract_rich_text_prop(props, "ID")
    if kb_id:
        return kb_id

    pid = page.get("id")
    if isinstance(pid, str) and pid.strip():
        return pid.replace("-", "")

    return None


def _truncate(s: str, max_chars: int) -> str:
    t = (s or "").strip()
    if len(t) <= int(max_chars):
        return t
    return t[: int(max_chars)].rstrip() + "…"


def _discover_title_property_from_schema(schema: Dict[str, Any]) -> str:
    # Try the common default.
    if isinstance(schema, dict):
        props = schema.get("properties")
        if isinstance(props, dict):
            # If "Name" exists and is title, prefer it.
            name_prop = props.get("Name")
            if isinstance(name_prop, dict) and name_prop.get("type") == "title":
                return "Name"
            for k, v in props.items():
                if (
                    isinstance(k, str)
                    and k.strip()
                    and isinstance(v, dict)
                    and v.get("type") == "title"
                ):
                    return k.strip()
    return "Name"


def map_notion_page_to_kb_entry(
    page: Dict[str, Any],
    title_prop_name: str = "Name",
    content_prop_name: str = "Content",
) -> Optional[KBEntry]:
    props = page.get("properties")
    if not isinstance(props, dict):
        return None

    # Status filter (required): only allow Status == "active" when Status exists.
    status_exists, status_name = _extract_status_value(props)
    if (
        status_exists
        and isinstance(status_name, str)
        and status_name.lower() != "active"
    ):
        return None

    # Optional allowlist for Source property (case-insensitive).
    allowed_sources = _env_allowed_sources()
    if allowed_sources is not None:
        src_name = _extract_source(props)
        if isinstance(src_name, str) and src_name.strip():
            if src_name.strip().lower() not in allowed_sources:
                return None

    kb_id = _extract_kb_id(page, props)
    if not kb_id:
        return None

    title = _extract_title_prop(props, title_prop_name) or _extract_title_prop(
        props, "Name"
    )
    if not title:
        # Fallback: first title-typed property on the page.
        for prop_name, prop in props.items():
            if (
                isinstance(prop_name, str)
                and isinstance(prop, dict)
                and prop.get("type") == "title"
            ):
                title = _extract_title_prop(props, prop_name)
                if title:
                    break

    content = _extract_rich_text_prop(props, content_prop_name)
    if not content:
        # Fallback: concat all rich_text properties (best-effort, budgeted).
        chunks: List[str] = []
        for prop_name, prop in props.items():
            if not (isinstance(prop_name, str) and isinstance(prop, dict)):
                continue
            if prop.get("type") != "rich_text":
                continue
            txt = _extract_rich_text_prop(props, prop_name)
            if txt:
                chunks.append(txt)
        content = "\n".join(chunks).strip()
    if not content:
        return None

    tags = _extract_multi_select(props, "Tags")
    applies_to_raw = _extract_multi_select(props, "AppliesTo")
    applies_to = [
        x.strip().lower() for x in applies_to_raw if isinstance(x, str) and x.strip()
    ]
    if not applies_to:
        applies_to = ["all"]

    updated_at = _extract_date_start(props, "UpdatedAt")
    if not updated_at:
        le = page.get("last_edited_time")
        updated_at = le.strip() if isinstance(le, str) and le.strip() else None

    src = _extract_source(props)
    snippet = _truncate(content, 240)

    # Priority is legacy/optional; keep stable default.
    priority = _extract_number(props, "Priority")
    if priority is None:
        priority = 0.5

    out: KBEntry = {
        "id": kb_id,
        "title": title,
        "tags": tags,
        "applies_to": applies_to,
        "priority": float(priority),
        "content": content,
        "updated_at": updated_at,
    }
    # Optional fields
    out["snippet"] = snippet
    if isinstance(status_name, str) and status_name.strip():
        out["status"] = status_name.strip()
    if isinstance(src, str) and src.strip():
        out["source"] = src.strip()
    return out


class KBNotionStore(KBStore):
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
        self._base_url = (
            base_url or os.getenv("NOTION_API_BASE_URL") or "https://api.notion.com"
        ).strip()
        self._notion_version = (
            notion_version or os.getenv("NOTION_VERSION") or "2022-06-28"
        ).strip()
        # Contract default is 60s; support legacy env as fallback.
        self._ttl = (
            int(cache_ttl_seconds)
            if cache_ttl_seconds is not None
            else _env_int("KB_TTL_SECONDS", _env_int("KB_NOTION_CACHE_TTL_SECONDS", 60))
        )
        self._timeout = timeout_seconds
        self._transport = transport
        self._last_meta: Dict[str, Any] = {}

    def _headers(self) -> Dict[str, str]:
        token = _get_notion_token()
        if not token:
            raise KBNotionReadFail("Missing NOTION_TOKEN/NOTION_API_KEY")
        return {
            "Authorization": f"Bearer {token}",
            "Notion-Version": self._notion_version,
            "Content-Type": "application/json",
        }

    def _schema_discovery_enabled(self) -> bool:
        # Keep tests deterministic/offline and compatible with MockTransport
        # handlers that only mock the /query endpoint.
        if (os.getenv("TESTING") or "").strip() == "1" or (
            "PYTEST_CURRENT_TEST" in os.environ
        ):
            return False

        # If a custom transport is injected (common in tests), avoid extra
        # schema calls unless explicitly enabled.
        if self._transport is not None:
            return (
                os.getenv("KB_NOTION_SCHEMA_DISCOVERY") or ""
            ).strip().lower() == "true"

        # Default: enabled in real HTTP mode.
        return True

    async def _get_database_schema(self, db_id: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._headers(),
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            r = await client.get(f"/v1/databases/{db_id}")
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, dict) else {}

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

    async def _fetch_entries_once(self) -> Tuple[List[KBEntry], str, str]:
        """Returns (entries_all, hash, last_fetch_iso)."""

        if not self._db_id:
            raise KBNotionReadFail("Missing NOTION_KB_DB_ID")

        # Best-effort schema discovery for title property.
        title_prop = "Name"
        if self._schema_discovery_enabled():
            try:
                schema = await self._get_database_schema(self._db_id)
                if isinstance(schema, dict):
                    title_prop = _discover_title_property_from_schema(schema)
            except Exception:
                title_prop = "Name"

        pages = await self._query_pages()

        entries: List[KBEntry] = []
        for p in pages:
            if not isinstance(p, dict):
                continue
            e = map_notion_page_to_kb_entry(p, title_prop)
            if e is None:
                continue
            entries.append(e)

        # Deterministic ordering
        entries.sort(key=lambda e: str(e.get("id") or ""))
        digest = _sha256_hex(entries)
        return entries, digest, _utc_iso()

    async def _fetch_entries_with_retry(self) -> Tuple[List[KBEntry], str, str]:
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

    async def load_all(self, *, force: bool = False) -> Dict[str, Any]:
        """Load ALL KB entries (normalized), using TTL cache.

        Contract:
        - If cache exists and TTL not expired and force=False -> do not call Notion.
        - If TTL expired or force=True -> fetch from Notion and refresh cache.
        """

        if not self._db_id:
            self._last_meta = {
                "mode": "notion",
                "ttl_s": int(max(int(self._ttl), 0)),
                "fetched_at": 0.0,
                "last_fetch_iso": None,
                "total_entries": 0,
                "hash": None,
                "kb_error": "missing_NOTION_KB_DB_ID",
            }
            raise KBNotionReadFail("NOTION_KB_DB_ID is required when KB_SOURCE=notion")

        db_key = self._db_id
        now = time.time()
        ttl_s = int(max(int(self._ttl), 0))

        do_fetch = False
        with _CACHE_LOCK:
            cache = _CACHE_BY_DB.get(db_key) or {}
            cached_entries = cache.get("entries_all")
            fetched_at = float(cache.get("fetched_at") or 0.0)

            if (
                not force
                and isinstance(cached_entries, list)
                and ttl_s > 0
                and (now - fetched_at) < float(ttl_s)
            ):
                meta = {
                    "mode": "notion",
                    "ttl_s": int(ttl_s),
                    "fetched_at": float(fetched_at),
                    "last_fetch_iso": cache.get("last_fetch_iso"),
                    "total_entries": int(len(cached_entries)),
                    "hash": cache.get("hash"),
                    "cache_hit": True,
                }
                self._last_meta = dict(meta)
                return {"entries": list(cached_entries), "meta": meta}

            fut = _IN_FLIGHT_BY_DB.get(db_key)
            if fut is not None and not fut.done():
                # Another thread/event-loop is fetching.
                pass
            else:
                fut = concurrent.futures.Future()
                _IN_FLIGHT_BY_DB[db_key] = fut
                do_fetch = True

        if not do_fetch:
            try:
                entries, digest, last_fetch_iso = await asyncio.wrap_future(fut)
                meta = {
                    "mode": "notion",
                    "ttl_s": int(ttl_s),
                    "fetched_at": float(
                        _CACHE_BY_DB.get(db_key, {}).get("fetched_at") or 0.0
                    ),
                    "last_fetch_iso": last_fetch_iso,
                    "total_entries": int(len(entries)),
                    "hash": digest,
                    "cache_hit": True,
                }
                self._last_meta = dict(meta)
                return {"entries": list(entries), "meta": meta}
            except Exception as exc:  # noqa: BLE001
                raise KBNotionReadFail(str(exc))

        try:
            entries, digest, last_fetch_iso = await self._fetch_entries_with_retry()
            fetched_at = time.time()
            with _CACHE_LOCK:
                _CACHE_BY_DB[db_key] = {
                    "entries_all": list(entries),
                    "fetched_at": float(fetched_at),
                    "ttl_s": int(ttl_s),
                    "hash": digest,
                    "last_fetch_iso": last_fetch_iso,
                }
                fut2 = _IN_FLIGHT_BY_DB.get(db_key)
                _IN_FLIGHT_BY_DB.pop(db_key, None)
                if fut2 is not None and not fut2.done():
                    fut2.set_result((entries, digest, last_fetch_iso))

            meta = {
                "mode": "notion",
                "ttl_s": int(ttl_s),
                "fetched_at": float(fetched_at),
                "last_fetch_iso": last_fetch_iso,
                "total_entries": int(len(entries)),
                "hash": digest,
                "cache_hit": False,
            }
            self._last_meta = dict(meta)
            return {"entries": list(entries), "meta": meta}
        except Exception as exc:  # noqa: BLE001
            with _CACHE_LOCK:
                fut2 = _IN_FLIGHT_BY_DB.get(db_key)
                _IN_FLIGHT_BY_DB.pop(db_key, None)
                if fut2 is not None and not fut2.done():
                    try:
                        fut2.set_exception(exc)
                    except Exception:
                        pass
            raise KBNotionReadFail(str(exc))

    async def search(
        self,
        query: str,
        *,
        top_k: int = 8,
        force: bool = False,
        intent: Optional[str] = None,
    ) -> Dict[str, Any]:
        from services.text_normalization import (  # noqa: PLC0415
            kb_entry_searchable_text,
            normalize_text,
            tokenize_normalized,
        )

        loaded = await self.load_all(force=force)
        entries_all = loaded.get("entries") if isinstance(loaded, dict) else []
        meta0 = loaded.get("meta") if isinstance(loaded, dict) else {}

        q = (query or "").strip()
        q_norm = normalize_text(q)
        q_toks = tokenize_normalized(q)

        # Prevent low-signal matches.
        low_signal = {"plan", "plans", "planning"}
        # Very small stopword list for common "explain" prompts; keep minimal.
        stop = {
            "kao",
            "da",
            "sam",
            "si",
            "smo",
            "ste",
            "su",
            "ali",
            "samo",
            "objasni",
            "objasnite",
            "koristi",
        }
        q_toks_sig = [
            t
            for t in q_toks
            if isinstance(t, str)
            and len(t) >= 3
            and t not in low_signal
            and t not in stop
        ]
        q_toks_sig_set = set(q_toks_sig)
        q_has_wysiati = "wysiati" in set(q_toks)

        intent_norm = (intent or "").strip().lower()
        gate_enabled = intent_norm in {"advisory", "state_query", "identity"}

        def _entry_applies_to(entry: KBEntry) -> List[str]:
            raw = entry.get("applies_to")
            if isinstance(raw, list):
                out = [
                    str(x).strip().lower()
                    for x in raw
                    if isinstance(x, str) and str(x).strip()
                ]
                return out or ["all"]
            return ["all"]

        hits: List[Tuple[int, int, int, int, str, KBEntry]] = []
        if q_norm and isinstance(entries_all, list):
            for e in entries_all:
                if not isinstance(e, dict):
                    continue

                if gate_enabled:
                    applies_to = _entry_applies_to(e)
                    if (intent_norm not in applies_to) and ("all" not in applies_to):
                        continue

                entry_id = str(e.get("id") or "")
                title_raw = str(e.get("title") or "")
                title_norm = normalize_text(title_raw)

                search_raw = kb_entry_searchable_text(e)
                search_norm = normalize_text(search_raw)

                id_norm = normalize_text(entry_id)
                id_title_tokens = set(tokenize_normalized(f"{id_norm} {title_norm}"))

                # Primary: full-phrase match on normalized text.
                title_hit = 1 if q_norm in title_norm else 0
                phrase_hit = q_norm in search_norm

                # Secondary: token overlap on normalized tokens.
                token_hit = False
                content_tokens: set[str] = set()
                if not phrase_hit and (q_toks_sig or q_has_wysiati):
                    content_tokens = set(tokenize_normalized(search_norm))

                    # Must-include rule: if query mentions WYSIATI, include matching entry.
                    must_include = False
                    if q_has_wysiati and (
                        "wysiati" in id_title_tokens or "wysiati" in content_tokens
                    ):
                        must_include = True
                        token_hit = True

                    if not token_hit and q_toks_sig:
                        overlap_total = sum(
                            1 for t in q_toks_sig_set if t in content_tokens
                        )
                        overlap_id_title = sum(
                            1 for t in q_toks_sig_set if t in id_title_tokens
                        )

                        if len(q_toks_sig) >= 2:
                            token_hit = overlap_total >= 2 or (
                                overlap_total >= 1 and overlap_id_title >= 1
                            )
                        else:
                            token_hit = overlap_total >= 1
                else:
                    must_include = False

                if not (phrase_hit or token_hit):
                    continue

                occurrences = search_norm.count(q_norm) if q_norm else 0
                _id = entry_id

                # Ranking bias: prefer direct id/title token matches.
                id_title_hits = (
                    sum(1 for t in q_toks_sig_set if t in id_title_tokens)
                    if q_toks_sig_set
                    else 0
                )

                hits.append(
                    (
                        1 if must_include else 0,
                        id_title_hits,
                        title_hit,
                        occurrences,
                        _id,
                        e,
                    )
                )

        # Sort: must-include first, then id/title token matches, then title phrase hits,
        # then occurrences desc, then stable by id.
        hits.sort(key=lambda t: (-t[0], -t[1], -t[2], -t[3], t[4]))

        top_k_i = int(top_k) if int(top_k) > 0 else 8
        selected = [e for _, _, _, _, _, e in hits[:top_k_i]]

        used_ids: List[str] = []
        for e in selected:
            _id = e.get("id")
            if isinstance(_id, str) and _id.strip():
                used_ids.append(_id.strip())

        meta: Dict[str, Any] = {
            "mode": (meta0.get("mode") if isinstance(meta0, dict) else None)
            or "notion",
            "ttl_s": meta0.get("ttl_s") if isinstance(meta0, dict) else None,
            "fetched_at": meta0.get("fetched_at") if isinstance(meta0, dict) else None,
            "last_fetch_iso": meta0.get("last_fetch_iso")
            if isinstance(meta0, dict)
            else None,
            "total_entries": int(meta0.get("total_entries") or 0)
            if isinstance(meta0, dict)
            else 0,
            "hit_count": int(len(selected)),
            "hash": meta0.get("hash") if isinstance(meta0, dict) else None,
        }
        self._last_meta = dict(meta)
        return {"entries": selected, "used_entry_ids": used_ids, "meta": meta}

    async def get_entries(self, ctx: Optional[Dict[str, Any]] = None) -> List[KBEntry]:
        # Back-compat for existing loaders.
        out = await self.load_all(force=False)
        entries = out.get("entries") if isinstance(out, dict) else []
        return entries if isinstance(entries, list) else []

    def get_meta(self) -> Dict[str, Any]:
        # Back-compat shape; keep at least these keys.
        meta = self._last_meta if isinstance(self._last_meta, dict) else {}
        return {
            "source": "notion",
            "cache_hit": bool(meta.get("cache_hit"))
            if isinstance(meta, dict)
            else False,
            "last_sync": meta.get("last_fetch_iso") if isinstance(meta, dict) else None,
            **(dict(meta) if isinstance(meta, dict) else {}),
        }


def _reset_cache_for_tests() -> None:
    """Test hook. Not part of runtime contract."""
    with _CACHE_LOCK:
        _CACHE_BY_DB.clear()
        _IN_FLIGHT_BY_DB.clear()


def clear_kb_notion_process_cache() -> None:
    """Clear process-local KB Notion cache.

    This is safe to call in production. It does not perform any IO.
    """

    with _CACHE_LOCK:
        _CACHE_BY_DB.clear()
        _IN_FLIGHT_BY_DB.clear()


# Back-compat alias
NotionKBStore = KBNotionStore
