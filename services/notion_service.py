# services/notion_service.py
from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from models.ai_command import AICommand

logger = logging.getLogger(__name__)


# ============================================================
# SINGLETON (SSOT)
# ============================================================
_NOTION_SERVICE: Optional["NotionService"] = None

_SINGLETON_NOT_INITIALIZED_MSG = "NotionService singleton is not initialized"

# Canonical ENV keys (SSOT per gateway/gateway_server.py)
_ENV_NOTION_API_KEY = "NOTION_API_KEY"
_ENV_NOTION_TOKEN_FALLBACK = "NOTION_TOKEN"
_ENV_GOALS_DB_ID = "NOTION_GOALS_DB_ID"
_ENV_TASKS_DB_ID = "NOTION_TASKS_DB_ID"
_ENV_PROJECTS_DB_ID = "NOTION_PROJECTS_DB_ID"


def set_notion_service(service: "NotionService") -> None:
    global _NOTION_SERVICE
    _NOTION_SERVICE = service


def get_notion_service() -> "NotionService":
    """
    SSOT throwing accessor. Do not change this contract.
    """
    if _NOTION_SERVICE is None:
        raise RuntimeError(_SINGLETON_NOT_INITIALIZED_MSG)
    return _NOTION_SERVICE


def get_or_init_notion_service() -> Optional["NotionService"]:
    """
    Enterprise helper:
    - If singleton already set -> return it
    - Else try init from env (if all required env vars exist) -> set + return
    - Else return None (fail-soft)
    """
    global _NOTION_SERVICE
    if _NOTION_SERVICE is not None:
        return _NOTION_SERVICE

    api_key = (os.getenv("NOTION_API_KEY") or "").strip()
    goals = (os.getenv("NOTION_GOALS_DB_ID") or "").strip()
    tasks = (os.getenv("NOTION_TASKS_DB_ID") or "").strip()
    projects = (os.getenv("NOTION_PROJECTS_DB_ID") or "").strip()

    if not (api_key and goals and tasks and projects):
        return None

    svc = NotionService(
        api_key=api_key,
        goals_db_id=goals,
        tasks_db_id=tasks,
        projects_db_id=projects,
    )
    _NOTION_SERVICE = svc
    return svc


def try_get_notion_service() -> Optional["NotionService"]:
    """
    SSOT non-throwing accessor (fail-soft).
    """
    return _NOTION_SERVICE


def init_notion_service_from_env_or_raise() -> "NotionService":
    """
    SSOT initializer used by gateway bootstrap.

    Mirrors gateway_server.py:
      - REQUIRED_ENV_VARS expects NOTION_API_KEY + NOTION_*_DB_ID (goals/tasks/projects)
      - NOTION_TOKEN is allowed as fallback in actual init

    Raises on missing/invalid env. No logging here; caller decides.
    """
    api_key = (
        os.getenv(_ENV_NOTION_API_KEY) or os.getenv(_ENV_NOTION_TOKEN_FALLBACK) or ""
    ).strip()
    goals_db_id = (os.getenv(_ENV_GOALS_DB_ID) or "").strip()
    tasks_db_id = (os.getenv(_ENV_TASKS_DB_ID) or "").strip()
    projects_db_id = (os.getenv(_ENV_PROJECTS_DB_ID) or "").strip()

    if not api_key:
        raise RuntimeError(f"Missing ENV var: {_ENV_NOTION_API_KEY}")
    if not goals_db_id:
        raise RuntimeError(f"Missing ENV var: {_ENV_GOALS_DB_ID}")
    if not tasks_db_id:
        raise RuntimeError(f"Missing ENV var: {_ENV_TASKS_DB_ID}")
    if not projects_db_id:
        raise RuntimeError(f"Missing ENV var: {_ENV_PROJECTS_DB_ID}")

    svc = NotionService(
        api_key=api_key,
        goals_db_id=goals_db_id,
        tasks_db_id=tasks_db_id,
        projects_db_id=projects_db_id,
    )
    set_notion_service(svc)
    return svc


def bootstrap_notion_service_from_env(
    *, force: bool = False
) -> Optional["NotionService"]:
    """
    Best-effort initializer for CLI / tests that bypass gateway bootstrap.

    - No logging (prevents spam; caller should write trace signals)
    - No raise (returns None on failure)
    - Does nothing if already initialized unless force=True
    """
    global _NOTION_SERVICE

    if _NOTION_SERVICE is not None and not force:
        return _NOTION_SERVICE

    try:
        return init_notion_service_from_env_or_raise()
    except Exception:
        return None


# ============================================================
# INTERNAL HELPERS
# ============================================================
def _utc_iso() -> str:
    return datetime.utcnow().isoformat()


def _ensure_dict(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _ensure_str(x: Any) -> str:
    return x.strip() if isinstance(x, str) else ""


def _as_bool(x: Any) -> bool:
    return bool(x is True)


@dataclass
class _DbSchemaCacheEntry:
    fetched_at: float
    schema: Dict[str, Any]


# ============================================================
# NOTION SERVICE (PRODUCTION CANONICAL)
# ============================================================
class NotionService:
    """
    NotionService â€” production-safe minimal SSOT wrapper.

    Key contracts used by your repo:
      - constructed via NotionService(api_key, goals_db_id, tasks_db_id, projects_db_id)
      - exposes .db_ids mapping (keys: goals/tasks/projects)
      - async execute(ai_command) -> dict
      - async sync_knowledge_snapshot() (best-effort; must not crash boot)
      - async query_database(db_key, query) used by bulk query + snapshot readers
      - async aclose() for lifespan shutdown

    NOTE:
      - execute() must accept exactly one positional arg after self (ai_command).
    """

    NOTION_BASE_URL = "https://api.notion.com/v1"
    NOTION_VERSION = "2022-06-28"

    def __init__(
        self,
        *,
        api_key: str,
        goals_db_id: str,
        tasks_db_id: str,
        projects_db_id: str,
    ) -> None:
        api_key = (api_key or "").strip()
        if not api_key:
            raise RuntimeError("NotionService requires api_key")

        self._api_key = api_key
        self._client: Optional[httpx.AsyncClient] = None

        # Canonical db map
        self.goals_db_id = (goals_db_id or "").strip()
        self.tasks_db_id = (tasks_db_id or "").strip()
        self.projects_db_id = (projects_db_id or "").strip()

        self.db_ids: Dict[str, str] = {}
        if self.goals_db_id:
            self.db_ids["goals"] = self.goals_db_id
        if self.tasks_db_id:
            self.db_ids["tasks"] = self.tasks_db_id
        if self.projects_db_id:
            self.db_ids["projects"] = self.projects_db_id

        # Schema cache (db_id -> schema)
        self._db_schema_cache: Dict[str, _DbSchemaCacheEntry] = {}
        self._db_schema_ttl_seconds = int(
            (os.getenv("NOTION_DB_SCHEMA_TTL_SECONDS") or "600").strip() or "600"
        )

        # Users cache for people resolution
        self._users_cache: Dict[str, Any] = {}
        self._users_cache_fetched_at: float = 0.0
        self._users_cache_ttl_seconds = int(
            (os.getenv("NOTION_USERS_CACHE_TTL_SECONDS") or "600").strip() or "600"
        )

    # ----------------------------
    # lifecycle
    # ----------------------------
    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Notion-Version": self.NOTION_VERSION,
            "Content-Type": "application/json",
        }
        self._client = httpx.AsyncClient(headers=headers, timeout=30.0)
        return self._client

    async def aclose(self) -> None:
        c = self._client
        self._client = None
        if c is not None:
            try:
                await c.aclose()
            except Exception:
                logger.warning("NotionService client close failed", exc_info=True)

    # ----------------------------
    # preflight (enterprise)
    # ----------------------------
    async def preflight_can_write(self) -> Dict[str, Any]:
        """Best-effort readiness check used before arming Notion Ops.

        Goals:
        - validate API key works (users/me)
        - validate DB ids are accessible
        - validate minimal expected properties exist (Name title)

        Returns:
          {"ok": True, ...} or {"ok": False, "reason": ..., "detail": ...}
        """
        # 1) Auth check
        try:
            me = await self._safe_request("GET", f"{self.NOTION_BASE_URL}/users/me")
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "reason": "notion_auth_failed",
                "detail": f"{type(exc).__name__}: {exc}",
            }

        # 2) Schema checks
        missing: Dict[str, Any] = {}
        for db_key, db_id in (
            ("goals", self.goals_db_id),
            ("tasks", self.tasks_db_id),
            ("projects", self.projects_db_id),
        ):
            db_id = (db_id or "").strip()
            if not db_id:
                missing[db_key] = {"reason": "missing_db_id"}
                continue

            try:
                schema = await self._get_database_schema(db_id)
            except Exception as exc:  # noqa: BLE001
                missing[db_key] = {
                    "reason": "schema_fetch_failed",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
                continue

            props = schema.get("properties") if isinstance(schema, dict) else None
            if not isinstance(props, dict) or not props:
                missing[db_key] = {"reason": "schema_missing_properties"}
                continue

            # Minimal expectation: there is at least one title property.
            # (Notion allows renaming the title property; do not hardcode "Name".)
            title_props = [
                k
                for k, v in props.items()
                if isinstance(k, str)
                and isinstance(v, dict)
                and (v.get("type") == "title")
            ]
            if not title_props:
                missing[db_key] = {
                    "reason": "missing_title_property",
                    "required_type": "title",
                }

        if missing:
            return {
                "ok": False,
                "reason": "notion_schema_not_ready",
                "missing": missing,
                "me": {
                    "id": me.get("id") if isinstance(me, dict) else None,
                    "name": me.get("name") if isinstance(me, dict) else None,
                },
            }

        return {
            "ok": True,
            "me": {
                "id": me.get("id") if isinstance(me, dict) else None,
                "name": me.get("name") if isinstance(me, dict) else None,
            },
            "db_ids": {
                "goals": self.goals_db_id,
                "tasks": self.tasks_db_id,
                "projects": self.projects_db_id,
            },
        }

    # ----------------------------
    # http wrapper
    # ----------------------------
    async def _safe_request(
        self,
        method: str,
        url: str,
        *,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        client = await self._get_client()

        try:
            resp = await client.request(
                method,
                url,
                params=params,
                json=payload,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Notion request failed: {type(exc).__name__}: {exc}"
            ) from exc

        text = resp.text or ""
        if resp.status_code >= 400:
            raise RuntimeError(f"Notion HTTP {resp.status_code}: {text}")

        if not text.strip():
            return {}

        try:
            data = resp.json()
            return data if isinstance(data, dict) else {"data": data}
        except Exception:
            return {"raw": text}

    # ----------------------------
    # db schema discovery (robust mapping)
    # ----------------------------
    async def _get_database_schema(self, db_id: str) -> Dict[str, Any]:
        db_id = (db_id or "").strip()
        if not db_id:
            return {}

        now = time.time()
        cached = self._db_schema_cache.get(db_id)
        if cached and (now - cached.fetched_at) <= float(self._db_schema_ttl_seconds):
            return cached.schema

        url = f"{self.NOTION_BASE_URL}/databases/{db_id}"
        schema = await self._safe_request("GET", url, payload=None)

        self._db_schema_cache[db_id] = _DbSchemaCacheEntry(
            fetched_at=now, schema=schema
        )
        return schema

    async def _get_users_cache(self) -> Dict[str, Dict[str, str]]:
        """Fetch and cache Notion users for people resolution.

        Returns mapping:
          {"by_email": {lower(email): id}, "by_name": {lower(name): id}}
        """
        now = time.time()
        if self._users_cache and (now - self._users_cache_fetched_at) <= float(
            self._users_cache_ttl_seconds
        ):
            by_email = self._users_cache.get("by_email")
            by_name = self._users_cache.get("by_name")
            if isinstance(by_email, dict) and isinstance(by_name, dict):
                return self._users_cache  # type: ignore[return-value]

        url = f"{self.NOTION_BASE_URL}/users"
        try:
            data = await self._safe_request("GET", url)
        except Exception as exc:  # noqa: BLE001
            logger.warning("NotionService users fetch failed: %s", exc)
            self._users_cache = {"by_email": {}, "by_name": {}}
            self._users_cache_fetched_at = now
            return self._users_cache  # type: ignore[return-value]

        results = data.get("results") if isinstance(data, dict) else None
        by_email: Dict[str, str] = {}
        by_name: Dict[str, str] = {}
        if isinstance(results, list):
            for u in results:
                if not isinstance(u, dict):
                    continue
                uid = _ensure_str(u.get("id"))
                if not uid:
                    continue
                name = _ensure_str(u.get("name"))
                person = u.get("person") if isinstance(u.get("person"), dict) else None
                email = ""
                if isinstance(person, dict):
                    email = _ensure_str(person.get("email"))

                if email:
                    by_email[email.lower()] = uid
                if name:
                    by_name[name.lower()] = uid

        self._users_cache = {"by_email": by_email, "by_name": by_name}
        self._users_cache_fetched_at = now
        return self._users_cache  # type: ignore[return-value]

    async def _resolve_people_ids_best_effort(self, inputs: List[str]) -> List[str]:
        """Resolve a list of emails/names to Notion user IDs (best-effort)."""
        if not inputs:
            return []

        cache = await self._get_users_cache()
        by_email = cache.get("by_email") or {}
        by_name = cache.get("by_name") or {}
        ids: List[str] = []

        for raw in inputs:
            token = _ensure_str(raw)
            if not token:
                continue

            key = token.lower()
            uid = None

            # Email match (direct or last token)
            if "@" in token:
                email_token = token.strip().lower()
                uid = by_email.get(email_token)
                if uid is None:
                    parts = token.split()
                    if parts and "@" in parts[-1]:
                        cand = parts[-1].lower()
                        uid = by_email.get(cand)

            # Fallback by name
            if uid is None:
                uid = by_name.get(key)

            if uid and uid not in ids:
                ids.append(uid)

        return ids

    async def get_fields_schema(self, db_key: str) -> Dict[str, Any]:
        """Return a UI-friendly schema for a DB key.

        Output shape:
          { "Name": {"type": "title"}, "Status": {"type": "status", "options": [...]}, ... }

        This is best-effort:
          - uses cached schema when possible
          - may perform a read-only Notion API call
          - raises RuntimeError if db_key cannot be resolved
        """
        db_id = self._resolve_db_id(db_key)
        schema = await self._get_database_schema(db_id)
        props = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(props, dict):
            return {}

        out: Dict[str, Any] = {}
        for name, p in props.items():
            if not isinstance(name, str) or not name.strip():
                continue
            if not isinstance(p, dict):
                continue

            p_type = p.get("type")
            p_type = p_type.strip() if isinstance(p_type, str) else ""
            if not p_type:
                continue

            rec: Dict[str, Any] = {"type": p_type}

            if p_type == "select":
                sel = p.get("select")
                if isinstance(sel, dict) and isinstance(sel.get("options"), list):
                    opts = [o for o in sel.get("options") if isinstance(o, dict)]
                    names = [
                        o.get("name") for o in opts if isinstance(o.get("name"), str)
                    ]
                    rec["options"] = [n for n in names if n.strip()]

            if p_type == "status":
                st = p.get("status")
                if isinstance(st, dict) and isinstance(st.get("options"), list):
                    opts = [o for o in st.get("options") if isinstance(o, dict)]
                    names = [
                        o.get("name") for o in opts if isinstance(o.get("name"), str)
                    ]
                    rec["options"] = [n for n in names if n.strip()]

            if p_type == "relation":
                rel = p.get("relation")
                if isinstance(rel, dict) and isinstance(rel.get("database_id"), str):
                    rec["relation_db_id"] = rel.get("database_id")

            out[name.strip()] = rec

        return out

    async def _apply_wrapper_patch_to_property_specs(
        self,
        *,
        db_key: str,
        property_specs: Dict[str, Any],
        wrapper_patch: Dict[str, Any],
    ) -> None:
        """Apply user-provided field overrides using DB schema.

        This enables CEO Console "fill missing" to patch more than the legacy
        Status/Priority/Deadline set, while remaining schema-driven.

        Only properties present in the DB schema are applied.
        Relation/people are intentionally ignored (they require IDs).
        """
        if not isinstance(property_specs, dict):
            return
        if not isinstance(wrapper_patch, dict) or not wrapper_patch:
            return

        schema = await self.get_fields_schema(db_key)
        if not isinstance(schema, dict) or not schema:
            return

        def _as_str(v: Any) -> str:
            if v is None:
                return ""
            if isinstance(v, str):
                return v.strip()
            try:
                return str(v).strip()
            except Exception:
                return ""

        def _looks_like_iso_date(s: str) -> bool:
            return bool(s and re.fullmatch(r"\d{4}-\d{2}-\d{2}", s))

        for field_name, raw in wrapper_patch.items():
            if not isinstance(field_name, str) or not field_name.strip():
                continue
            fname = field_name.strip()
            if fname not in schema:
                continue

            st = schema.get(fname)
            st = st if isinstance(st, dict) else {}
            p_type = st.get("type")
            p_type = p_type.strip() if isinstance(p_type, str) else ""
            if not p_type:
                continue

            # Intentionally ignore types requiring IDs.
            if p_type in {"people", "relation", "created_by", "last_edited_by"}:
                continue

            if p_type == "title":
                s = _as_str(raw)
                if s:
                    property_specs[fname] = {"type": "title", "text": s}
                continue

            if p_type in {"rich_text", "text"}:
                s = _as_str(raw)
                if s:
                    property_specs[fname] = {"type": "rich_text", "text": s}
                continue

            if p_type in {"select", "status"}:
                s = _as_str(raw)
                if s:
                    property_specs[fname] = {"type": p_type, "name": s}
                continue

            if p_type == "multi_select":
                if isinstance(raw, list):
                    names = [_as_str(x) for x in raw if _as_str(x)]
                else:
                    s = _as_str(raw)
                    names = [x.strip() for x in s.split(",") if x.strip()] if s else []
                if names:
                    property_specs[fname] = {"type": "multi_select", "names": names}
                continue

            if p_type == "date":
                s = _as_str(raw)
                if not s:
                    continue
                iso = ""
                try:
                    from services.coo_translation_service import (  # noqa: PLC0415
                        COOTranslationService,
                    )

                    iso = COOTranslationService._try_parse_date_to_iso(s) or ""
                except Exception:
                    iso = ""
                if not iso and _looks_like_iso_date(s):
                    iso = s
                if iso:
                    property_specs[fname] = {"type": "date", "start": iso}
                continue

            if p_type == "number":
                try:
                    n = float(raw)
                    property_specs[fname] = {"type": "number", "number": n}
                except Exception:
                    pass
                continue

            if p_type == "checkbox":
                v = raw
                if isinstance(v, str):
                    sv = v.strip().lower()
                    if sv in {"true", "yes", "da", "1"}:
                        v = True
                    elif sv in {"false", "no", "ne", "0"}:
                        v = False
                if isinstance(v, bool):
                    property_specs[fname] = {"type": "checkbox", "checkbox": v}
                continue

    async def _resolve_property_type(self, *, db_id: str, prop_name: str) -> str:
        prop_name = (prop_name or "").strip()
        if not prop_name:
            return ""

        schema = await self._get_database_schema(db_id)
        props = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(props, dict):
            return ""

        p = props.get(prop_name)
        if not isinstance(p, dict):
            return ""

        t = p.get("type")
        return (t or "").strip() if isinstance(t, str) else ""

    async def _resolve_option_name(
        self, *, db_id: str, prop_name: str, desired: str
    ) -> str:
        """Resolve select/status option name in a case-insensitive way.

        Notion option names are case-sensitive; prompts aren't. This makes execution
        deterministic and reduces "sometimes it works" behavior.
        """
        desired = (desired or "").strip()
        if not desired:
            return desired

        schema = await self._get_database_schema(db_id)
        props = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(props, dict):
            return desired

        p = props.get(prop_name)
        if not isinstance(p, dict):
            return desired

        p_type = p.get("type")
        p_type = p_type.strip() if isinstance(p_type, str) else ""

        options: List[Dict[str, Any]] = []
        if p_type == "select":
            sel = p.get("select")
            if isinstance(sel, dict) and isinstance(sel.get("options"), list):
                options = [o for o in sel.get("options") if isinstance(o, dict)]
        elif p_type == "status":
            st = p.get("status")
            if isinstance(st, dict) and isinstance(st.get("options"), list):
                options = [o for o in st.get("options") if isinstance(o, dict)]

        if not options:
            return desired

        by_lower = {}
        for o in options:
            name = o.get("name")
            if isinstance(name, str) and name.strip():
                by_lower[name.strip().lower()] = name.strip()

        return by_lower.get(desired.lower(), desired)

    # ----------------------------
    # property_specs -> Notion API properties
    # ----------------------------
    def _title_prop(self, text: str) -> Dict[str, Any]:
        text = (text or "").strip()
        return {"title": [{"text": {"content": text}}]}

    def _rich_text_prop(self, text: str) -> Dict[str, Any]:
        text = (text or "").strip()
        return {"rich_text": [{"text": {"content": text}}]}

    def _select_prop(self, name: str) -> Dict[str, Any]:
        name = (name or "").strip()
        return {"select": {"name": name}} if name else {"select": None}

    def _status_prop(self, name: str) -> Dict[str, Any]:
        name = (name or "").strip()
        return {"status": {"name": name}} if name else {"status": None}

    async def _build_properties_from_property_specs(
        self,
        *,
        db_id: str,
        property_specs: Dict[str, Any],
        warnings: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Robust rule:
          - If spec.type == "status" but DB schema says property is "select",
            map to select.
          - Added support for "date" type
        """
        out: Dict[str, Any] = {}
        if not isinstance(property_specs, dict) or not property_specs:
            return out

        for prop_name, spec in property_specs.items():
            if not isinstance(prop_name, str) or not prop_name.strip():
                continue
            if not isinstance(spec, dict):
                continue

            pn = prop_name.strip()
            stype = _ensure_str(spec.get("type")).lower()

            if stype == "title":
                txt = _ensure_str(spec.get("text") or spec.get("value") or "")
                out[pn] = self._title_prop(txt)
                continue

            if stype in ("rich_text", "text"):
                txt = _ensure_str(spec.get("text") or spec.get("value") or "")
                out[pn] = self._rich_text_prop(txt)
                continue

            if stype == "select":
                name = _ensure_str(spec.get("name") or spec.get("value") or "")
                resolved = await self._resolve_option_name(
                    db_id=db_id, prop_name=pn, desired=name
                )
                out[pn] = self._select_prop(resolved)
                continue

            if stype == "status":
                name = _ensure_str(spec.get("name") or spec.get("value") or "")
                actual = await self._resolve_property_type(db_id=db_id, prop_name=pn)
                resolved = await self._resolve_option_name(
                    db_id=db_id, prop_name=pn, desired=name
                )
                if actual == "select":
                    out[pn] = self._select_prop(resolved)
                else:
                    out[pn] = self._status_prop(resolved)
                continue

            if stype == "date":
                date_str = _ensure_str(spec.get("start") or spec.get("value") or "")
                out[pn] = self._date_prop(date_str)
                continue

            if stype == "people":
                # Supported forms:
                #  a) {"type": "people", "ids": [..]}
                #  b) {"type": "people", "emails": [..]}
                #  c) {"type": "people", "names": [..]}
                #  d) {"type": "people", "value": "email or name"}
                ids: List[str] = []

                raw_ids = spec.get("ids")
                if isinstance(raw_ids, list):
                    ids = [_ensure_str(x) for x in raw_ids if _ensure_str(x)]

                if not ids:
                    tokens: List[str] = []
                    for key in ("emails", "names"):
                        raw_list = spec.get(key)
                        if isinstance(raw_list, list):
                            tokens.extend(
                                [_ensure_str(x) for x in raw_list if _ensure_str(x)]
                            )

                    if not tokens:
                        raw_value = spec.get("value") or spec.get("name") or ""
                        s_val = _ensure_str(raw_value)
                        if s_val:
                            tokens = [t.strip() for t in s_val.split(",") if t.strip()]

                    if tokens:
                        ids = await self._resolve_people_ids_best_effort(tokens)
                        if not ids and warnings is not None:
                            for tok in tokens:
                                warnings.append(f"people_not_resolved:{tok}")

                if ids:
                    out[pn] = {"people": [{"id": pid} for pid in ids]}
                continue

            # Unknown types ignored by design (safety)
            continue

        return out

    # ----------------------------
    # database id resolution
    # ----------------------------
    def _resolve_db_id(self, db_key: str) -> str:
        k = (db_key or "").strip()
        if not k:
            raise RuntimeError("db_key is required")

        # Allow passing raw database UUID-ish (already normalized elsewhere)
        if k.count("-") >= 4:
            return k

        lk = k.lower()
        if lk in self.db_ids and self.db_ids[lk].strip():
            return self.db_ids[lk].strip()

        for candidate in (lk, lk.rstrip("s"), lk + "s"):
            v = self.db_ids.get(candidate)
            if isinstance(v, str) and v.strip():
                return v.strip()

        raise RuntimeError(f"Unknown db_key: {db_key}")

    # ============================================================
    # PUBLIC API
    # ============================================================
    async def sync_knowledge_snapshot(self) -> Dict[str, Any]:
        """
        Best-effort: do not break boot if Notion is unreachable.
        """
        try:
            from services.knowledge_snapshot_service import KnowledgeSnapshotService

            snap = KnowledgeSnapshotService.get_snapshot()
            if isinstance(snap, dict):
                snap.setdefault("trace", {})
                snap["trace"]["notion_sync"] = {"ok": True, "ts": _utc_iso()}
                snap["ready"] = True
                snap["last_sync"] = _utc_iso()
                KnowledgeSnapshotService.update_snapshot(snap)
            return {"ok": True}
        except Exception:
            logger.warning("sync_knowledge_snapshot failed (non-fatal)", exc_info=True)
            return {"ok": False}

    async def query_database(
        self, *, db_key: str, query: Dict[str, Any]
    ) -> Dict[str, Any]:
        db_id = self._resolve_db_id(db_key)
        url = f"{self.NOTION_BASE_URL}/databases/{db_id}/query"
        payload = query if isinstance(query, dict) else {}
        res = await self._safe_request("POST", url, payload=payload)
        res.setdefault("database_id", db_id)
        return res

    @staticmethod
    def _extract_page_title(page: Dict[str, Any], prop_name: str = "Name") -> str:
        try:
            props = page.get("properties")
            if not isinstance(props, dict):
                return ""
            prop = props.get(prop_name)
            if not isinstance(prop, dict):
                return ""
            title_arr = prop.get("title")
            if not isinstance(title_arr, list):
                return ""
            parts = []
            for t in title_arr:
                if isinstance(t, dict):
                    txt = t.get("plain_text")
                    if isinstance(txt, str) and txt:
                        parts.append(txt)
            return "".join(parts).strip()
        except Exception:
            return ""

    async def _resolve_page_id_by_title_best_effort(
        self, *, db_key: str, title: str
    ) -> Dict[str, Any]:
        """Resolve a Notion page_id by human title (best-effort, safe).

        Returns dict:
          {"ok": bool, "page_id": str|None, "reason": str|None}
        """
        t = (title or "").strip()
        if not t:
            return {"ok": False, "page_id": None, "reason": "empty_title"}

        # Query by contains, then pick exact (case-insensitive) if possible.
        try:
            res = await self.query_database(
                db_key=db_key,
                query={
                    "page_size": 10,
                    "filter": {"property": "Name", "title": {"contains": t}},
                },
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "page_id": None,
                "reason": f"query_failed:{exc}",
            }

        items = res.get("results") if isinstance(res, dict) else None
        if not isinstance(items, list) or not items:
            return {"ok": False, "page_id": None, "reason": "not_found"}

        normalized = t.casefold()
        candidates = []
        for p in items:
            if not isinstance(p, dict):
                continue
            pid = _ensure_str(p.get("id"))
            if not pid:
                continue
            name = self._extract_page_title(p, "Name")
            candidates.append((pid, name))

        # Prefer exact title match (case-insensitive)
        exact = [
            (pid, name) for (pid, name) in candidates if name.casefold() == normalized
        ]
        chosen_pool = exact if exact else candidates

        if len(chosen_pool) == 1:
            return {"ok": True, "page_id": chosen_pool[0][0], "reason": None}

        # Ambiguous: multiple matches
        names = [name for (_, name) in chosen_pool if name]
        names_preview = ", ".join(names[:5])
        return {
            "ok": False,
            "page_id": None,
            "reason": f"ambiguous:{names_preview}" if names_preview else "ambiguous",
        }

    async def execute(self, ai_command: Any) -> Dict[str, Any]:
        """
        Canonical executor entrypoint called by NotionOpsAgent / Orchestrator.
        """
        cmd = _ensure_dict(
            ai_command.model_dump() if hasattr(ai_command, "model_dump") else {}
        )
        if not cmd:
            cmd = {
                "command": getattr(ai_command, "command", None),
                "intent": getattr(ai_command, "intent", None),
                "params": getattr(ai_command, "params", None),
                "execution_id": getattr(ai_command, "execution_id", None),
                "approval_id": getattr(ai_command, "approval_id", None),
                "read_only": getattr(ai_command, "read_only", None),
                "metadata": getattr(ai_command, "metadata", None),
            }

        command = _ensure_str(cmd.get("command"))
        intent = _ensure_str(cmd.get("intent"))
        params = _ensure_dict(cmd.get("params"))
        execution_id = _ensure_str(cmd.get("execution_id"))
        approval_id = _ensure_str(cmd.get("approval_id"))
        read_only = _as_bool(cmd.get("read_only"))
        metadata = _ensure_dict(cmd.get("metadata"))

        logger.info(
            "NotionService.execute intent=%s execution_id=%s approval_id=%s",
            intent or command,
            execution_id,
            approval_id,
        )

        if read_only:
            return {
                "ok": True,
                "execution_state": "COMPLETED",
                "read_only": True,
                "result": {"message": "read_only_noop"},
                "execution_id": execution_id or None,
                "approval_id": approval_id or None,
            }

        if intent == "create_page":
            return await self._execute_create_page(
                params=params,
                execution_id=execution_id,
                approval_id=approval_id,
                metadata=metadata,
            )

        if intent == "create_goal":
            return await self._execute_create_goal(
                params=params,
                execution_id=execution_id,
                approval_id=approval_id,
                metadata=metadata,
            )

        if intent == "create_task":
            return await self._execute_create_task(
                params=params,
                execution_id=execution_id,
                approval_id=approval_id,
                metadata=metadata,
            )

        if intent == "create_project":
            return await self._execute_create_project(
                params=params,
                execution_id=execution_id,
                approval_id=approval_id,
                metadata=metadata,
            )

        if intent == "update_page":
            return await self._execute_update_page(
                params=params,
                execution_id=execution_id,
                approval_id=approval_id,
                metadata=metadata,
            )

        # Enterprise: batch/branch requests (grouped operations)
        if intent in {"batch_request", "batch", "branch_request"}:
            return await self._execute_batch_request(
                params=params,
                execution_id=execution_id,
                approval_id=approval_id,
                metadata=metadata,
            )

        # Enterprise: delete = archive (Notion has no hard delete)
        if intent == "delete_page":
            return await self._execute_delete_page(
                params=params,
                execution_id=execution_id,
                approval_id=approval_id,
                metadata=metadata,
            )

        raise RuntimeError(f"Unsupported intent: {intent or '(empty)'}")

    async def _execute_batch_request(
        self,
        *,
        params: Dict[str, Any],
        execution_id: str,
        approval_id: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Execute a batch of Notion operations under a single approval.

        Supported input shapes:
          - {"operations": [{"op_id": "...", "intent": "create_task", "payload": {...}}, ...]}
          - {"operations": [{"intent": "update_page", "params": {...}}, ...]}

        Reference resolution:
          - Any string value equal to "$<op_id>" or starting with "$<op_id>" is replaced
            with the created Notion page_id from a previous operation.
        """

        operations = params.get("operations")
        if not isinstance(operations, list) or not operations:
            raise RuntimeError("batch_request requires operations[]")

        wrapper_patch = params.get("wrapper_patch")
        wrapper_patch = wrapper_patch if isinstance(wrapper_patch, dict) else None

        ref_map: Dict[str, str] = {}
        results: List[Dict[str, Any]] = []

        def _resolve_refs(v: Any) -> Any:
            if isinstance(v, str) and v.startswith("$") and len(v) > 1:
                key = v[1:]
                return ref_map.get(key, v)
            if isinstance(v, list):
                return [_resolve_refs(x) for x in v]
            if isinstance(v, dict):
                return {k: _resolve_refs(x) for k, x in v.items()}
            return v

        for idx, op in enumerate(operations):
            if not isinstance(op, dict):
                results.append(
                    {
                        "index": idx,
                        "ok": False,
                        "reason": "invalid_operation_shape",
                        "detail": "operation must be an object",
                    }
                )
                continue

            op_id = _ensure_str(op.get("op_id"))
            op_intent = _ensure_str(op.get("intent"))

            # payload or params
            op_params = op.get("payload")
            if not isinstance(op_params, dict):
                op_params = op.get("params")
            op_params = _ensure_dict(op_params)
            op_params = _resolve_refs(op_params)

            # Propagate wrapper_patch to sub-operations so create_* can apply schema-backed fills.
            if (
                wrapper_patch
                and isinstance(op_params, dict)
                and "wrapper_patch" not in op_params
            ):
                op_params["wrapper_patch"] = wrapper_patch

            if not op_intent:
                results.append(
                    {
                        "index": idx,
                        "op_id": op_id or None,
                        "ok": False,
                        "reason": "missing_intent",
                    }
                )
                continue

            try:
                sub_exec_id = f"{execution_id}:{idx}" if execution_id else ""
                sub = AICommand(
                    command="notion_write",
                    intent=op_intent,
                    params=op_params,
                    approval_id=approval_id,
                    execution_id=sub_exec_id,
                    read_only=False,
                    metadata={
                        **(metadata or {}),
                        "batch": True,
                        "batch_index": idx,
                        "batch_op_id": op_id or None,
                    },
                )
                sub_res = await self.execute(sub)

                # capture created ids for reference resolution
                page_id = ""
                if isinstance(sub_res, dict):
                    r = sub_res.get("result")
                    if isinstance(r, dict):
                        page_id = _ensure_str(r.get("page_id") or r.get("id") or "")
                if op_id and page_id:
                    ref_map[op_id] = page_id

                results.append(
                    {
                        "index": idx,
                        "op_id": op_id or None,
                        "intent": op_intent,
                        "ok": True,
                        "page_id": page_id or None,
                        "result": sub_res,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "index": idx,
                        "op_id": op_id or None,
                        "intent": op_intent,
                        "ok": False,
                        "reason": str(exc),
                        "error_type": exc.__class__.__name__,
                    }
                )

        ok_all = all(
            (isinstance(r, dict) and r.get("ok") is True) for r in results
        ) and bool(results)
        return {
            "ok": ok_all,
            "execution_state": "COMPLETED" if ok_all else "FAILED",
            "read_only": False,
            "execution_id": execution_id or None,
            "approval_id": approval_id or None,
            "result": {
                "intent": "batch_request",
                "total": len(results),
                "success": sum(
                    1 for r in results if isinstance(r, dict) and r.get("ok") is True
                ),
                "failed": sum(
                    1 for r in results if isinstance(r, dict) and r.get("ok") is False
                ),
                "operations": results,
                "ref_map": ref_map,
            },
            "metadata": metadata,
        }

    async def _execute_delete_page(
        self,
        *,
        params: Dict[str, Any],
        execution_id: str,
        approval_id: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Archive a Notion page ("delete" in common language)."""
        page_id = _ensure_str(params.get("page_id"))
        if not page_id:
            raise RuntimeError("delete_page requires page_id")

        url = f"{self.NOTION_BASE_URL}/pages/{page_id}"
        res = await self._safe_request("PATCH", url, payload={"archived": True})

        page_url = _ensure_str(res.get("url"))
        return {
            "ok": True,
            "execution_state": "COMPLETED",
            "read_only": False,
            "execution_id": execution_id or None,
            "approval_id": approval_id or None,
            "result": {
                "intent": "delete_page",
                "page_id": page_id,
                "url": page_url or None,
                "raw": res,
            },
            "metadata": metadata,
        }

    async def _execute_create_page(
        self,
        *,
        params: Dict[str, Any],
        execution_id: str,
        approval_id: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        db_key = _ensure_str(params.get("db_key") or params.get("database") or "")
        if not db_key:
            raise RuntimeError("create_page requires db_key and properties")

        db_id = self._resolve_db_id(db_key)

        wrapper_patch = params.get("wrapper_patch")

        properties = params.get("properties")
        if isinstance(properties, dict) and properties:
            notion_properties = properties
        else:
            property_specs = params.get("property_specs")
            if not isinstance(property_specs, dict) or not property_specs:
                raise RuntimeError("create_page requires db_key and properties")

            if isinstance(wrapper_patch, dict) and wrapper_patch:
                await self._apply_wrapper_patch_to_property_specs(
                    db_key=db_key,
                    property_specs=property_specs,
                    wrapper_patch=wrapper_patch,
                )
            notion_properties = await self._build_properties_from_property_specs(
                db_id=db_id, property_specs=property_specs
            )
            if not notion_properties:
                raise RuntimeError("create_page requires db_key and properties")

        payload = {"parent": {"database_id": db_id}, "properties": notion_properties}
        url = f"{self.NOTION_BASE_URL}/pages"
        res = await self._safe_request("POST", url, payload=payload)

        page_id = _ensure_str(res.get("id"))
        page_url = _ensure_str(res.get("url"))

        return {
            "ok": True,
            "execution_state": "COMPLETED",
            "read_only": False,
            "execution_id": execution_id or None,
            "approval_id": approval_id or None,
            "result": {
                "intent": "create_page",
                "db_key": db_key,
                "database_id": db_id,
                "page_id": page_id or None,
                "url": page_url or None,
                "raw": res,
            },
            "metadata": metadata,
        }

    async def _execute_create_goal(
        self,
        *,
        params: Dict[str, Any],
        execution_id: str,
        approval_id: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a goal in Notion goals database."""
        db_key = "goals"
        db_id = self._resolve_db_id(db_key)

        # Extract goal properties from params
        title = _ensure_str(params.get("title"))
        if not title:
            raise RuntimeError("create_goal requires title")

        # Build property specs
        property_specs: Dict[str, Any] = {"Name": {"type": "title", "text": title}}

        # Optional fields
        description = _ensure_str(params.get("description"))
        if description:
            property_specs["Description"] = {"type": "rich_text", "text": description}

        deadline = _ensure_str(params.get("deadline"))
        if deadline:
            property_specs["Deadline"] = {"type": "date", "start": deadline}

        priority = _ensure_str(params.get("priority"))
        if priority:
            property_specs["Priority"] = {"type": "select", "name": priority}

        status = _ensure_str(params.get("status"))
        if status:
            property_specs["Status"] = {"type": "status", "name": status}

        # Allow explicit property_specs to augment/override defaults (e.g., people)
        extra_specs = params.get("property_specs")
        if isinstance(extra_specs, dict) and extra_specs:
            property_specs.update(extra_specs)

        wrapper_patch = params.get("wrapper_patch")
        if isinstance(wrapper_patch, dict) and wrapper_patch:
            await self._apply_wrapper_patch_to_property_specs(
                db_key=db_key,
                property_specs=property_specs,
                wrapper_patch=wrapper_patch,
            )

        # Build Notion properties
        notion_properties = await self._build_properties_from_property_specs(
            db_id=db_id, property_specs=property_specs
        )

        payload = {"parent": {"database_id": db_id}, "properties": notion_properties}
        url = f"{self.NOTION_BASE_URL}/pages"
        res = await self._safe_request("POST", url, payload=payload)

        page_id = _ensure_str(res.get("id"))
        page_url = _ensure_str(res.get("url"))

        return {
            "ok": True,
            "execution_state": "COMPLETED",
            "read_only": False,
            "execution_id": execution_id or None,
            "approval_id": approval_id or None,
            "result": {
                "intent": "create_goal",
                "db_key": db_key,
                "database_id": db_id,
                "page_id": page_id or None,
                "url": page_url or None,
                "raw": res,
            },
            "metadata": metadata,
        }

    async def _execute_create_task(
        self,
        *,
        params: Dict[str, Any],
        execution_id: str,
        approval_id: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a task in Notion tasks database."""
        db_key = "tasks"
        db_id = self._resolve_db_id(db_key)

        # Extract task properties from params
        title = _ensure_str(params.get("title"))
        if not title:
            raise RuntimeError("create_task requires title")

        # Build property specs
        property_specs: Dict[str, Any] = {"Name": {"type": "title", "text": title}}

        # Optional fields
        description = _ensure_str(params.get("description"))
        if description:
            property_specs["Description"] = {"type": "rich_text", "text": description}

        deadline = _ensure_str(params.get("deadline"))
        if deadline:
            property_specs["Deadline"] = {"type": "date", "start": deadline}

        priority = _ensure_str(params.get("priority"))
        if priority:
            property_specs["Priority"] = {"type": "select", "name": priority}

        status = _ensure_str(params.get("status"))
        if status:
            property_specs["Status"] = {"type": "status", "name": status}

        # Allow explicit property_specs to augment/override defaults (e.g., people)
        extra_specs = params.get("property_specs")
        if isinstance(extra_specs, dict) and extra_specs:
            property_specs.update(extra_specs)

        wrapper_patch = params.get("wrapper_patch")
        if isinstance(wrapper_patch, dict) and wrapper_patch:
            await self._apply_wrapper_patch_to_property_specs(
                db_key=db_key,
                property_specs=property_specs,
                wrapper_patch=wrapper_patch,
            )

        # Collect warnings from property_specs resolution and relation linking
        warnings: List[str] = []

        # Build Notion properties
        notion_properties = await self._build_properties_from_property_specs(
            db_id=db_id, property_specs=property_specs, warnings=warnings
        )

        # Handle relations after page creation
        goal_id = _ensure_str(params.get("goal_id"))
        project_id = _ensure_str(params.get("project_id"))

        payload = {"parent": {"database_id": db_id}, "properties": notion_properties}
        url = f"{self.NOTION_BASE_URL}/pages"
        res = await self._safe_request("POST", url, payload=payload)

        page_id = _ensure_str(res.get("id"))
        page_url = _ensure_str(res.get("url"))

        # Best-effort: allow linking by title when ID wasn't provided.
        if not goal_id:
            goal_title = _ensure_str(params.get("goal_title") or "")
            if goal_title:
                rr = await self._resolve_page_id_by_title_best_effort(
                    db_key="goals", title=goal_title
                )
                if rr.get("ok") is True and _ensure_str(rr.get("page_id")):
                    goal_id = _ensure_str(rr.get("page_id"))
                else:
                    warnings.append(
                        f"goal_link_not_resolved:{_ensure_str(rr.get('reason') or '')}"
                    )

        # Update relations if provided
        if goal_id or project_id:
            await self._update_page_relations(
                page_id=page_id,
                goal_id=goal_id,
                project_id=project_id,
            )

        return {
            "ok": True,
            "execution_state": "COMPLETED",
            "read_only": False,
            "execution_id": execution_id or None,
            "approval_id": approval_id or None,
            "result": {
                "intent": "create_task",
                "db_key": db_key,
                "database_id": db_id,
                "page_id": page_id or None,
                "url": page_url or None,
                "raw": res,
                "warnings": warnings,
            },
            "metadata": metadata,
        }

    async def _execute_create_project(
        self,
        *,
        params: Dict[str, Any],
        execution_id: str,
        approval_id: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Create a project in Notion projects database."""
        db_key = "projects"
        db_id = self._resolve_db_id(db_key)

        # Extract project properties from params
        title = _ensure_str(params.get("title"))
        if not title:
            raise RuntimeError("create_project requires title")

        # Build property specs
        property_specs: Dict[str, Any] = {"Name": {"type": "title", "text": title}}

        # Optional fields
        description = _ensure_str(params.get("description"))
        if description:
            property_specs["Description"] = {"type": "rich_text", "text": description}

        deadline = _ensure_str(params.get("deadline"))
        if deadline:
            property_specs["Deadline"] = {"type": "date", "start": deadline}

        priority = _ensure_str(params.get("priority"))
        if priority:
            property_specs["Priority"] = {"type": "select", "name": priority}

        status = _ensure_str(params.get("status"))
        if status:
            property_specs["Status"] = {"type": "status", "name": status}

        # Allow explicit property_specs to augment/override defaults (e.g., people)
        extra_specs = params.get("property_specs")
        if isinstance(extra_specs, dict) and extra_specs:
            property_specs.update(extra_specs)

        wrapper_patch = params.get("wrapper_patch")
        if isinstance(wrapper_patch, dict) and wrapper_patch:
            await self._apply_wrapper_patch_to_property_specs(
                db_key=db_key,
                property_specs=property_specs,
                wrapper_patch=wrapper_patch,
            )

        # Collect warnings from property_specs resolution and relation linking
        warnings: List[str] = []

        # Build Notion properties
        notion_properties = await self._build_properties_from_property_specs(
            db_id=db_id, property_specs=property_specs, warnings=warnings
        )

        # Handle relations after page creation
        primary_goal_id = _ensure_str(params.get("primary_goal_id"))

        payload = {"parent": {"database_id": db_id}, "properties": notion_properties}
        url = f"{self.NOTION_BASE_URL}/pages"
        res = await self._safe_request("POST", url, payload=payload)

        page_id = _ensure_str(res.get("id"))
        page_url = _ensure_str(res.get("url"))

        if not primary_goal_id:
            goal_title = _ensure_str(params.get("primary_goal_title") or "")
            if goal_title:
                rr = await self._resolve_page_id_by_title_best_effort(
                    db_key="goals", title=goal_title
                )
                if rr.get("ok") is True and _ensure_str(rr.get("page_id")):
                    primary_goal_id = _ensure_str(rr.get("page_id"))
                else:
                    warnings.append(
                        f"primary_goal_link_not_resolved:{_ensure_str(rr.get('reason') or '')}"
                    )

        # Update relations if provided
        if primary_goal_id:
            await self._update_page_relations(
                page_id=page_id,
                goal_id=primary_goal_id,
            )

        return {
            "ok": True,
            "execution_state": "COMPLETED",
            "read_only": False,
            "execution_id": execution_id or None,
            "approval_id": approval_id or None,
            "result": {
                "intent": "create_project",
                "db_key": db_key,
                "database_id": db_id,
                "page_id": page_id or None,
                "url": page_url or None,
                "raw": res,
                "warnings": warnings,
            },
            "metadata": metadata,
        }

    async def _execute_update_page(
        self,
        *,
        params: Dict[str, Any],
        execution_id: str,
        approval_id: str,
        metadata: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Update an existing page in Notion."""
        page_id = _ensure_str(params.get("page_id"))
        if not page_id:
            raise RuntimeError("update_page requires page_id")

        # Build property specs from update params
        property_specs: Dict[str, Any] = {}

        title = _ensure_str(params.get("title"))
        if title:
            property_specs["Name"] = {"type": "title", "text": title}

        description = _ensure_str(params.get("description"))
        if description:
            property_specs["Description"] = {"type": "rich_text", "text": description}

        deadline = _ensure_str(params.get("deadline"))
        if deadline:
            property_specs["Deadline"] = {"type": "date", "start": deadline}

        priority = _ensure_str(params.get("priority"))
        if priority:
            property_specs["Priority"] = {"type": "select", "name": priority}

        status = _ensure_str(params.get("status"))
        if status:
            property_specs["Status"] = {"type": "status", "name": status}

        # Get the database ID from params or infer from page
        db_key = _ensure_str(params.get("db_key"))
        db_id = ""
        if db_key:
            db_id = self._resolve_db_id(db_key)

        # Build Notion properties
        notion_properties = {}
        if property_specs and db_id:
            notion_properties = await self._build_properties_from_property_specs(
                db_id=db_id, property_specs=property_specs
            )

        # Update the page
        payload: Dict[str, Any] = {}
        if notion_properties:
            payload["properties"] = notion_properties

        url = f"{self.NOTION_BASE_URL}/pages/{page_id}"
        res = await self._safe_request("PATCH", url, payload=payload)

        page_url = _ensure_str(res.get("url"))

        # Update relations if provided
        goal_id = _ensure_str(params.get("goal_id"))
        project_id = _ensure_str(params.get("project_id"))
        if goal_id or project_id:
            await self._update_page_relations(
                page_id=page_id,
                goal_id=goal_id,
                project_id=project_id,
            )

        return {
            "ok": True,
            "execution_state": "COMPLETED",
            "read_only": False,
            "execution_id": execution_id or None,
            "approval_id": approval_id or None,
            "result": {
                "intent": "update_page",
                "page_id": page_id,
                "url": page_url or None,
                "raw": res,
            },
            "metadata": metadata,
        }

    async def _update_page_relations(
        self,
        *,
        page_id: str,
        goal_id: str = "",
        project_id: str = "",
    ) -> None:
        """Update relations for a page (goal and/or project)."""
        if not page_id:
            return

        properties: Dict[str, Any] = {}

        if goal_id:
            properties["Goal"] = {"relation": [{"id": goal_id}]}

        if project_id:
            properties["Project"] = {"relation": [{"id": project_id}]}

        if not properties:
            return

        url = f"{self.NOTION_BASE_URL}/pages/{page_id}"
        payload = {"properties": properties}
        await self._safe_request("PATCH", url, payload=payload)

    def _date_prop(self, date_str: str) -> Dict[str, Any]:
        """Build a date property."""
        date_str = (date_str or "").strip()
        if not date_str:
            return {"date": None}
        return {"date": {"start": date_str}}

    def _relation_prop(self, page_ids: List[str]) -> Dict[str, Any]:
        """Build a relation property."""
        if not page_ids:
            return {"relation": []}
        return {"relation": [{"id": pid} for pid in page_ids if pid]}
