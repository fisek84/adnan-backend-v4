# services/notion_service.py
from __future__ import annotations

import contextvars
import logging
import os
import re
import time
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

import httpx

from models.ai_command import AICommand

logger = logging.getLogger(__name__)


# ============================================================
# NOTION BUDGET CONTEXT (READ PATH ONLY)
# ============================================================


class NotionBudgetExceeded(RuntimeError):
    def __init__(self, *, kind: str, detail: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(kind)
        self.kind = kind
        self.detail = detail or {}


@dataclass
class _NotionBudgetState:
    max_calls: Optional[int]
    max_latency_ms: Optional[int]
    started_at: float
    calls: int = 0
    exceeded: bool = False
    exceeded_kind: Optional[str] = None
    exceeded_detail: Dict[str, Any] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.exceeded_detail is None:
            self.exceeded_detail = {}

    def _check_deadline_only(self) -> None:
        if self.max_latency_ms is None:
            return
        if self.max_latency_ms < 0:
            return
        elapsed_ms = int(round((time.monotonic() - self.started_at) * 1000.0))
        if elapsed_ms > int(self.max_latency_ms):
            self.exceeded = True
            self.exceeded_kind = "max_latency_ms"
            self.exceeded_detail = {
                "elapsed_ms": elapsed_ms,
                "limit_ms": int(self.max_latency_ms),
            }
            raise NotionBudgetExceeded(
                kind="max_latency_ms", detail=self.exceeded_detail
            )

    def check_and_consume_call(self) -> None:
        # Latency check first (if we've already blown the window, do not spend a call).
        self._check_deadline_only()

        if self.max_calls is None:
            self.calls += 1
            return
        if self.max_calls < 0:
            self.calls += 1
            return

        if self.calls >= int(self.max_calls):
            self.exceeded = True
            self.exceeded_kind = "max_calls"
            self.exceeded_detail = {
                "calls": int(self.calls),
                "limit": int(self.max_calls),
            }
            raise NotionBudgetExceeded(kind="max_calls", detail=self.exceeded_detail)

        self.calls += 1


_NOTION_BUDGET_STATE: contextvars.ContextVar[Optional[_NotionBudgetState]] = (
    contextvars.ContextVar("notion_budget_state", default=None)
)


def env_int(name: str, default: int) -> int:
    raw = (os.getenv(name) or "").strip()
    try:
        return int(raw)
    except Exception:
        return int(default)


@asynccontextmanager
async def notion_budget_context(*, max_calls: int, max_latency_ms: int):
    state = _NotionBudgetState(
        max_calls=int(max_calls),
        max_latency_ms=int(max_latency_ms),
        started_at=time.monotonic(),
    )
    token = _NOTION_BUDGET_STATE.set(state)
    try:
        yield state
    finally:
        _NOTION_BUDGET_STATE.reset(token)


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


def discover_notion_db_registry_from_env() -> (
    tuple[Dict[str, str], Dict[str, Dict[str, Any]], List[str]]
):
    """SSOT: discover all configured Notion DB ids from environment.

    Canon:
      - Prefer `NOTION_<KEY>_DB_ID`.
      - Support legacy alias `NOTION_<KEY>_DATABASE_ID` only as fallback.
      - Allow JSON extension via `NOTION_EXTRA_DATABASES_JSON='{"my_db":"<id>"}'`.

    Returns:
      - db_ids: {db_key: db_id}
      - meta: {db_key: {"db_id": str, "env_name": str, "legacy_alias": bool}}
      - warnings: list[str] (deprecation / conflicts)

    Never raises.
    """

    db_ids: Dict[str, str] = {}
    meta: Dict[str, Dict[str, Any]] = {}
    warnings: List[str] = []

    # Collect both variants first.
    db_id_vars: Dict[str, str] = {}
    database_id_vars: Dict[str, str] = {}

    for name, value in os.environ.items():
        if not isinstance(name, str) or not name.startswith("NOTION_"):
            continue
        if not isinstance(value, str):
            continue
        v = value.strip()
        if not v:
            continue

        if name.endswith("_DB_ID"):
            logical = name[len("NOTION_") : -len("_DB_ID")].strip()
            if logical:
                db_id_vars[logical.upper()] = v
            continue

        if name.endswith("_DATABASE_ID"):
            logical = name[len("NOTION_") : -len("_DATABASE_ID")].strip()
            if logical:
                database_id_vars[logical.upper()] = v
            continue

    all_keys = sorted(set(db_id_vars.keys()) | set(database_id_vars.keys()))
    for logical in all_keys:
        key = logical.lower()
        db_id = db_id_vars.get(logical)
        database_id = database_id_vars.get(logical)

        if db_id:
            db_ids[key] = db_id
            meta[key] = {
                "db_id": db_id,
                "env_name": f"NOTION_{logical}_DB_ID",
                "legacy_alias": False,
            }
            if database_id and database_id != db_id:
                warnings.append(
                    f"Both NOTION_{logical}_DB_ID and NOTION_{logical}_DATABASE_ID are set; using _DB_ID and ignoring legacy alias."
                )
            elif database_id and database_id == db_id:
                warnings.append(
                    f"Legacy alias NOTION_{logical}_DATABASE_ID is set but deprecated; prefer NOTION_{logical}_DB_ID."
                )
            continue

        if database_id:
            db_ids[key] = database_id
            meta[key] = {
                "db_id": database_id,
                "env_name": f"NOTION_{logical}_DATABASE_ID",
                "legacy_alias": True,
            }
            warnings.append(
                f"Deprecated env var NOTION_{logical}_DATABASE_ID detected; please migrate to NOTION_{logical}_DB_ID."
            )

    extra_json = (os.getenv("NOTION_EXTRA_DATABASES_JSON", "") or "").strip()
    if extra_json:
        try:
            import json  # noqa: PLC0415

            extra = json.loads(extra_json)
            if isinstance(extra, dict):
                for k, v in extra.items():
                    if isinstance(k, str) and isinstance(v, str) and v.strip():
                        kk = k.strip().lower()
                        vv = v.strip()
                        db_ids[kk] = vv
                        meta[kk] = {
                            "db_id": vv,
                            "env_name": "NOTION_EXTRA_DATABASES_JSON",
                            "legacy_alias": False,
                        }
        except Exception:
            warnings.append(
                "NOTION_EXTRA_DATABASES_JSON present but invalid JSON; ignoring"
            )

    return db_ids, meta, warnings


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
    NotionService Ă˘â‚¬â€ť production-safe minimal SSOT wrapper.

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
        # Enterprise: httpx AsyncClient is effectively tied to the event loop.
        # Keep one client per running loop to avoid cross-loop reuse/close issues.
        self._clients_by_loop: Dict[int, httpx.AsyncClient] = {}

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

        # Enterprise: auto-discover all configured Notion DBs from env.
        # This allows notion_write/create_page to target ANY db_key that has
        # NOTION_<KEY>_DB_ID / NOTION_<KEY>_DATABASE_ID set.
        try:
            for k, v in self._discover_all_db_keys_from_env().items():
                if (
                    isinstance(k, str)
                    and isinstance(v, str)
                    and k.strip()
                    and v.strip()
                ):
                    self.db_ids.setdefault(k.strip().lower(), v.strip())
        except Exception:
            # Never break boot
            pass

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

    def clear_caches(self) -> None:
        """Clear internal in-memory caches.

        Safe to call in production; performs no IO.
        """

        try:
            self._db_schema_cache.clear()
        except Exception:
            pass
        try:
            self._users_cache.clear()
            self._users_cache_fetched_at = 0.0
        except Exception:
            pass

    @staticmethod
    def _discover_all_db_keys_from_env() -> Dict[str, str]:
        """Discover all Notion DB ids from env.

        Supports:
          - NOTION_<KEY>_DATABASE_ID
          - NOTION_<KEY>_DB_ID
          - NOTION_EXTRA_DATABASES_JSON='{"my_db":"<id>"}'
        """
        out, _, _warnings = discover_notion_db_registry_from_env()
        return out

    async def _filter_properties_payload_by_schema(
        self,
        *,
        db_id: str,
        properties: Dict[str, Any],
        warnings: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Filter a raw Notion API properties payload so we never send computed/unknown fields."""
        if not isinstance(properties, dict) or not properties:
            return {}

        schema = await self._get_database_schema(db_id)
        props = schema.get("properties") if isinstance(schema, dict) else None
        if not isinstance(props, dict) or not props:
            # Fail-soft: if schema unavailable, preserve legacy behavior.
            return properties

        computed_types = {
            "formula",
            "rollup",
            "created_time",
            "last_edited_time",
            "created_by",
            "last_edited_by",
            "unique_id",
        }
        valid_names = {k for k in props.keys() if isinstance(k, str) and k.strip()}
        by_cf = {k.casefold(): k for k in valid_names}

        out: Dict[str, Any] = {}
        for raw_name, val in properties.items():
            if not isinstance(raw_name, str) or not raw_name.strip():
                continue

            name = raw_name.strip()
            if name not in valid_names and name.casefold() in by_cf:
                name = by_cf[name.casefold()]

            if name not in valid_names:
                if warnings is not None:
                    warnings.append(f"unknown_property:{raw_name.strip()}")
                continue

            p = props.get(name)
            t = p.get("type") if isinstance(p, dict) else None
            t = t.strip() if isinstance(t, str) else ""
            if t in computed_types:
                if warnings is not None:
                    warnings.append(f"computed_field_ignored:{name}")
                continue

            out[name] = val

        return out

    # ----------------------------
    # lifecycle
    # ----------------------------
    async def _get_client(self) -> httpx.AsyncClient:
        try:
            loop_id = id(asyncio.get_running_loop())
        except Exception:
            loop_id = 0

        c = self._clients_by_loop.get(loop_id)
        if c is not None:
            return c

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Notion-Version": self.NOTION_VERSION,
            "Content-Type": "application/json",
        }
        c = httpx.AsyncClient(headers=headers, timeout=30.0)
        self._clients_by_loop[loop_id] = c
        return c

    def client_stats(self) -> Dict[str, Any]:
        """Lightweight diagnostics for observability/ops.

        Returns a small dict safe to include in traces/logs.
        """
        try:
            cur_loop_id = id(asyncio.get_running_loop())
        except Exception:
            cur_loop_id = None
        return {
            "clients_by_loop": len(self._clients_by_loop),
            "current_loop_id": cur_loop_id,
        }

    async def aclose_current_loop(self) -> None:
        """Close only the client bound to the current running event loop."""
        try:
            loop_id = id(asyncio.get_running_loop())
        except Exception:
            loop_id = 0

        c = self._clients_by_loop.pop(loop_id, None)
        if c is None:
            return
        try:
            await c.aclose()
        except Exception as exc:
            msg = str(exc)
            if isinstance(exc, RuntimeError) and "Event loop is closed" in msg:
                logger.debug(
                    "NotionService client close skipped (event loop closed)",
                    exc_info=True,
                )
            else:
                logger.warning("NotionService client close failed", exc_info=True)

    async def aclose(self) -> None:
        # Best-effort: close all known clients; cross-loop close may fail during teardown.
        clients = self._clients_by_loop
        self._clients_by_loop = {}
        for _, c in clients.items():
            try:
                await c.aclose()
            except Exception as exc:
                msg = str(exc)
                if isinstance(exc, RuntimeError) and "Event loop is closed" in msg:
                    logger.debug(
                        "NotionService client close skipped (event loop closed)",
                        exc_info=True,
                    )
                else:
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

        budget_state = _NOTION_BUDGET_STATE.get()
        if budget_state is not None:
            budget_state.check_and_consume_call()

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

        # IMPORTANT: do not let budget deadline checks mask definitive HTTP errors
        # (e.g., 401/403). Budget checks still apply for successful responses.
        text = resp.text or ""
        if resp.status_code >= 400:
            if budget_state is not None:
                try:
                    budget_state._check_deadline_only()
                except NotionBudgetExceeded:
                    pass
            raise RuntimeError(f"Notion HTTP {resp.status_code}: {text}")

        if budget_state is not None:
            budget_state._check_deadline_only()

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

            if p_type == "multi_select":
                ms = p.get("multi_select")
                if isinstance(ms, dict) and isinstance(ms.get("options"), list):
                    opts = [o for o in ms.get("options") if isinstance(o, dict)]
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
        warnings: Optional[List[str]] = None,
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

        try:
            from services.notion_patch_validation import (  # noqa: PLC0415
                SchemaNameResolver,
            )

            _resolver = SchemaNameResolver(schema)
        except Exception:
            _resolver = None

        def _resolve_schema_prop_name(raw_name: str) -> str:
            if _resolver is None:
                return ""
            return _resolver.resolve(raw_name)

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

            fname = _resolve_schema_prop_name(field_name)
            if not fname:
                if warnings is not None:
                    warnings.append(f"wrapper_patch_unknown_field:{field_name.strip()}")
                continue

            st = schema.get(fname)
            st = st if isinstance(st, dict) else {}
            p_type = st.get("type")
            p_type = p_type.strip() if isinstance(p_type, str) else ""
            if not p_type:
                continue

            # Intentionally ignore types requiring IDs unless explicitly supported.
            if p_type in {"created_by", "last_edited_by"}:
                if warnings is not None:
                    warnings.append(f"wrapper_patch_computed_field_ignored:{fname}")
                continue

            if p_type == "relation":
                # Wrapper_patch does not have a safe way to resolve relation IDs.
                if warnings is not None:
                    warnings.append(f"wrapper_patch_requires_ids:{fname}")
                continue

            if p_type == "people":
                # Accept comma-separated names/emails; execution will resolve to IDs best-effort.
                if isinstance(raw, list):
                    tokens = [_as_str(x) for x in raw if _as_str(x)]
                else:
                    s = _as_str(raw)
                    tokens = [x.strip() for x in s.split(",") if x.strip()] if s else []
                if tokens:
                    property_specs[fname] = {"type": "people", "names": tokens}
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
                    opts0 = st.get("options")
                    opts = (
                        [o for o in opts0 if isinstance(o, str) and o.strip()]
                        if isinstance(opts0, list)
                        else []
                    )
                    # Normalize option by case-insensitive match.
                    if opts and s not in opts:
                        cf = s.casefold()
                        matches = [o for o in opts if o.casefold() == cf]
                        if len(matches) == 1:
                            s = matches[0]
                        elif warnings is not None:
                            warnings.append(f"wrapper_patch_invalid_option:{fname}:{s}")
                    property_specs[fname] = {"type": p_type, "name": s}
                continue

            if p_type == "multi_select":
                if isinstance(raw, list):
                    names = [_as_str(x) for x in raw if _as_str(x)]
                else:
                    s = _as_str(raw)
                    names = [x.strip() for x in s.split(",") if x.strip()] if s else []
                if names:
                    opts0 = st.get("options")
                    opts = (
                        [o for o in opts0 if isinstance(o, str) and o.strip()]
                        if isinstance(opts0, list)
                        else []
                    )
                    if opts:
                        normed: List[str] = []
                        for n0 in names:
                            if n0 in opts:
                                normed.append(n0)
                                continue
                            cf = n0.casefold()
                            matches = [o for o in opts if o.casefold() == cf]
                            if len(matches) == 1:
                                normed.append(matches[0])
                            else:
                                normed.append(n0)
                                if warnings is not None:
                                    warnings.append(
                                        f"wrapper_patch_invalid_option:{fname}:{n0}"
                                    )
                        names = normed

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

        # Use DB schema as SSOT for:
        #  - property name normalization (case-insensitive + bilingual synonyms)
        #  - blocking computed fields
        schema = await self._get_database_schema(db_id)
        props = schema.get("properties") if isinstance(schema, dict) else None
        props = props if isinstance(props, dict) else {}

        prop_types: Dict[str, str] = {}
        for n, p in props.items():
            if not isinstance(n, str) or not n.strip():
                continue
            if isinstance(p, dict) and isinstance(p.get("type"), str):
                prop_types[n.strip()] = p.get("type").strip()

        prop_by_cf = {k.casefold(): k for k in prop_types.keys()}
        title_props = [k for k, t in prop_types.items() if t == "title"]
        computed_types = {
            "formula",
            "rollup",
            "created_time",
            "last_edited_time",
            "created_by",
            "last_edited_by",
            "unique_id",
        }

        schema_available = bool(prop_types)

        # Enforce local schema-registry read_only hints (enterprise SSOT)
        registry_read_only: set[str] = set()
        try:
            from services.notion_schema_registry import (  # noqa: PLC0415
                NotionSchemaRegistry,
            )

            schema_dict = None
            for _k, _v in NotionSchemaRegistry.__dict__.items():
                if (
                    isinstance(_v, dict)
                    and "tasks" in _v
                    and isinstance(_v.get("tasks"), dict)
                ):
                    schema_dict = _v
                    break

            if schema_dict and isinstance(db_id, str) and db_id.strip():
                _dbid = db_id.strip()
                for _db in schema_dict.values():
                    if not isinstance(_db, dict):
                        continue
                    if str(_db.get("db_id") or "").strip() != _dbid:
                        continue
                    p0 = _db.get("properties") or {}
                    if isinstance(p0, dict):
                        for _pn, _meta in p0.items():
                            if (
                                isinstance(_meta, dict)
                                and _meta.get("read_only") is True
                            ):
                                registry_read_only.add(str(_pn))
                    break
        except Exception:
            registry_read_only = set()
        if not schema_available:
            # Fail-soft: if schema can't be fetched (or tests stub it out),
            # do not drop fields. Preserve legacy behavior.
            computed_types = set()

        def _resolve_prop_name(raw_name: str) -> str:
            cand = (raw_name or "").strip()
            if not cand:
                return ""
            if not schema_available:
                return cand
            if cand in prop_types:
                return cand
            cf = cand.casefold()
            if cf in prop_by_cf:
                return prop_by_cf[cf]

            internal = ""
            try:
                from services.notion_keyword_mapper import (  # noqa: PLC0415
                    NotionKeywordMapper,
                )

                internal = NotionKeywordMapper.translate_property_name(cand)
                km = NotionKeywordMapper.normalize_field_name(cand)
                if isinstance(km, str) and km in prop_types:
                    return km
                if isinstance(km, str) and km.casefold() in prop_by_cf:
                    return prop_by_cf[km.casefold()]
            except Exception:
                internal = ""

            if internal in {"name", "title"} and title_props:
                return title_props[0]

            if internal == "due_date":
                if "Due Date" in prop_types:
                    return "Due Date"
                if "Deadline" in prop_types:
                    return "Deadline"
            if internal == "deadline":
                if "Deadline" in prop_types:
                    return "Deadline"
                if "Due Date" in prop_types:
                    return "Due Date"

            return ""

        def _multi_select_prop(names: List[str]) -> Dict[str, Any]:
            clean = [n.strip() for n in names if isinstance(n, str) and n.strip()]
            return {"multi_select": [{"name": n} for n in clean]}

        for prop_name, spec in property_specs.items():
            if not isinstance(prop_name, str) or not prop_name.strip():
                continue
            if not isinstance(spec, dict):
                continue

            resolved_name = _resolve_prop_name(prop_name)
            if not resolved_name:
                if warnings is not None:
                    warnings.append(f"unknown_property:{prop_name.strip()}")
                continue

            live_type = prop_types.get(resolved_name, "")
            if live_type in computed_types:
                if warnings is not None:
                    warnings.append(f"computed_field_ignored:{resolved_name}")
                continue

            pn = resolved_name
            if pn in registry_read_only:
                if warnings is not None:
                    warnings.append(f"read_only_field_ignored:{pn}")
                continue

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

            if stype == "number":
                raw_n = spec.get("number")
                if raw_n is None:
                    raw_n = spec.get("value")
                try:
                    out[pn] = {"number": float(raw_n)}
                except Exception:
                    if warnings is not None:
                        warnings.append(f"invalid_number:{pn}")
                continue

            if stype == "checkbox":
                raw_v = spec.get("checkbox")
                if raw_v is None:
                    raw_v = spec.get("value")
                v = raw_v
                if isinstance(v, str):
                    sv = v.strip().lower()
                    if sv in {"true", "yes", "da", "1"}:
                        v = True
                    elif sv in {"false", "no", "ne", "0"}:
                        v = False
                if isinstance(v, bool):
                    out[pn] = {"checkbox": v}
                else:
                    if warnings is not None:
                        warnings.append(f"invalid_checkbox:{pn}")
                continue

            if stype == "multi_select":
                raw_names = spec.get("names")
                if isinstance(raw_names, list):
                    out[pn] = _multi_select_prop([_ensure_str(x) for x in raw_names])
                else:
                    s_val = _ensure_str(spec.get("value") or "")
                    names = (
                        [x.strip() for x in s_val.split(",") if x.strip()]
                        if s_val
                        else []
                    )
                    out[pn] = _multi_select_prop(names)
                continue

            if stype == "relation":
                ids: List[str] = []
                raw_ids = spec.get("ids")
                if isinstance(raw_ids, list):
                    ids = [_ensure_str(x) for x in raw_ids if _ensure_str(x)]
                else:
                    raw_one = spec.get("id") or spec.get("value") or ""
                    s_one = _ensure_str(raw_one)
                    if s_one:
                        ids = [x.strip() for x in s_one.split(",") if x.strip()]
                if ids:
                    out[pn] = self._relation_prop(ids)
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

            # Unknown/unsupported spec types: never silent.
            if warnings is not None:
                warnings.append(f"unsupported_spec_type:{stype or '(empty)'}:{pn}")
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

    # ============================================================
    # READ-ONLY KNOWLEDGE SNAPSHOT (SSOT)
    # ============================================================
    async def build_knowledge_snapshot(
        self,
        *,
        db_keys: Optional[List[str]] = None,
        max_items_by_db: Optional[Dict[str, int]] = None,
    ) -> Dict[str, Any]:
        """Build a lightweight, UI-safe knowledge snapshot from Notion.

        Contract:
        - Read-only (queries only)
        - Best-effort (never raises)
        - Returns wrapper compatible with KnowledgeSnapshotService.update_snapshot:
            {"payload": {"goals": [], "tasks": [], "projects": [], "last_sync": ...},
             "meta": {"ok": bool, "synced_at": ... , "errors": [...]}}
        """

        def _title_prop_for_db_cached(db_id: str) -> str:
            """Best-effort title property without spending Notion calls.

            IMPORTANT: do not fetch schema here. Schema discovery is optional and
            expensive under strict budgets.
            """

            try:
                cached = self._db_schema_cache.get(db_id)
                schema = (
                    cached.schema
                    if cached and isinstance(cached.schema, dict)
                    else None
                )
                props = schema.get("properties") if isinstance(schema, dict) else None
                if isinstance(props, dict):
                    for k, v in props.items():
                        if (
                            isinstance(k, str)
                            and k.strip()
                            and isinstance(v, dict)
                            and v.get("type") == "title"
                        ):
                            return k
            except Exception:
                pass

            # Default (Notion common case)
            return "Name"

        # ------------------------------------------------------------
        # Snapshot item fields extraction (SSOT allowlist + capped)
        # ------------------------------------------------------------
        from services.snapshot_fields_allowlist import (  # noqa: PLC0415
            FieldSpec,
            allowlist_for_db_key,
        )

        MAX_ITEMS_PER_DB = 200
        MAX_FIELDS_PER_ROW = 50
        MAX_STRING_LEN = 500
        MAX_LIST_LEN = 50

        def _truncate_str(s: Any, max_len: int = MAX_STRING_LEN) -> str:
            if not isinstance(s, str):
                return ""
            txt = s.strip()
            if not txt:
                return ""
            if max_len <= 0:
                return ""
            if len(txt) <= max_len:
                return txt
            return txt[: max(0, max_len - 1)].rstrip() + "…"

        def _normalize_id(s: Any) -> str:
            ss = _ensure_str(s)
            return ss.replace("-", "") if ss else ""

        def _prop_plain_text(prop: Dict[str, Any]) -> str:
            # Notion title/rich_text: list of segments with plain_text.
            try:
                t = prop.get("type")
                if t == "title":
                    arr = prop.get("title")
                else:
                    arr = prop.get("rich_text")
                if not isinstance(arr, list):
                    return ""
                parts = []
                for seg in arr[:MAX_LIST_LEN]:
                    if isinstance(seg, dict):
                        pt = seg.get("plain_text")
                        if isinstance(pt, str) and pt.strip():
                            parts.append(pt.strip())
                return _truncate_str(" ".join(parts))
            except Exception:
                return ""

        def _prop_checkbox(prop: Dict[str, Any]) -> Optional[bool]:
            try:
                v = prop.get("checkbox")
                if isinstance(v, bool):
                    return bool(v)
                return None
            except Exception:
                return None

        def _prop_select_name(prop: Dict[str, Any]) -> str:
            try:
                sel = prop.get("select")
                if isinstance(sel, dict):
                    return _truncate_str(sel.get("name"))
                return ""
            except Exception:
                return ""

        def _prop_multi_select(prop: Dict[str, Any]) -> List[str]:
            try:
                arr = prop.get("multi_select")
                if not isinstance(arr, list):
                    return []
                out: List[str] = []
                for it in arr[:MAX_LIST_LEN]:
                    if isinstance(it, dict):
                        nm = it.get("name")
                        if isinstance(nm, str) and nm.strip():
                            out.append(_truncate_str(nm))
                return out
            except Exception:
                return []

        def _prop_status_name(prop: Dict[str, Any]) -> str:
            try:
                st = prop.get("status")
                if isinstance(st, dict):
                    return _truncate_str(st.get("name"))
                return ""
            except Exception:
                return ""

        def _prop_date_range(prop: Dict[str, Any]) -> Optional[Dict[str, str]]:
            try:
                dt = prop.get("date")
                if isinstance(dt, dict):
                    start = _truncate_str(dt.get("start"), 40)
                    end = _truncate_str(dt.get("end"), 40)
                    if start or end:
                        out: Dict[str, str] = {}
                        if start:
                            out["start"] = start
                        if end:
                            out["end"] = end
                        return out
                return None
            except Exception:
                return None

        def _prop_number(prop: Dict[str, Any]) -> Optional[float]:
            try:
                v = prop.get("number")
                if isinstance(v, (int, float)):
                    return float(v)
                return None
            except Exception:
                return None

        def _prop_formula_number(prop: Dict[str, Any]) -> Optional[float]:
            try:
                f = prop.get("formula")
                if not isinstance(f, dict):
                    return None
                if f.get("type") == "number" and isinstance(
                    f.get("number"), (int, float)
                ):
                    return float(f.get("number"))
                return None
            except Exception:
                return None

        def _prop_rollup_number(prop: Dict[str, Any]) -> Optional[float]:
            try:
                r = prop.get("rollup")
                if not isinstance(r, dict):
                    return None
                if r.get("type") == "number" and isinstance(
                    r.get("number"), (int, float)
                ):
                    return float(r.get("number"))
                return None
            except Exception:
                return None

        def _prop_people_ids(prop: Dict[str, Any]) -> List[str]:
            try:
                ppl = prop.get("people")
                if not isinstance(ppl, list):
                    return []
                out: List[str] = []
                for p in ppl[:MAX_LIST_LEN]:
                    if isinstance(p, dict):
                        # Deterministic preference: email -> name -> id
                        email = (
                            p.get("person", {}).get("email")
                            if isinstance(p.get("person"), dict)
                            else None
                        )
                        if isinstance(email, str) and email.strip():
                            out.append(_truncate_str(email.strip(), 120))
                            continue
                        nm = p.get("name")
                        if isinstance(nm, str) and nm.strip():
                            out.append(_truncate_str(nm.strip(), 120))
                            continue
                        pid = _normalize_id(p.get("id"))
                        if pid:
                            out.append(pid)

                # Sort for stability
                out2 = sorted([x for x in out if isinstance(x, str) and x.strip()])
                return out2[:MAX_LIST_LEN]
            except Exception:
                return []

        def _prop_relation_ids(prop: Dict[str, Any]) -> List[str]:
            try:
                rel = prop.get("relation")
                if not isinstance(rel, list):
                    return []
                out: List[str] = []
                for r in rel[:MAX_LIST_LEN]:
                    if isinstance(r, dict):
                        rid = _normalize_id(r.get("id"))
                        if rid:
                            out.append(rid)
                return sorted(out)[:MAX_LIST_LEN]
            except Exception:
                return []

        def _props_by_lower(page: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
            props = page.get("properties")
            if not isinstance(props, dict):
                return {}
            out: Dict[str, Dict[str, Any]] = {}
            for k, v in props.items():
                if isinstance(k, str) and k.strip() and isinstance(v, dict):
                    out[k.strip().lower()] = v
            return out

        def _pick_prop(
            props_lc: Dict[str, Dict[str, Any]], names: List[str]
        ) -> Optional[Dict[str, Any]]:
            for nm in names:
                key = (nm or "").strip().lower()
                if not key:
                    continue
                v = props_lc.get(key)
                if isinstance(v, dict):
                    return v
            return None

        def _extract_allowlisted_fields(
            db_key: str, page: Dict[str, Any]
        ) -> tuple[Dict[str, Any], bool]:
            """Return (fields, truncated_flag). Never raises."""
            try:
                allow = allowlist_for_db_key(db_key)
                if not allow:
                    return {}, False

                props_lc = _props_by_lower(page)
                out: Dict[str, Any] = {}
                truncated = False

                def _add_value(spec: FieldSpec) -> None:
                    nonlocal truncated

                    # Special: KPI numeric wildcard
                    if spec.kind == "kpi_numeric_all":
                        numeric: List[tuple[str, float]] = []
                        for prop_name_lc, prop in props_lc.items():
                            if not isinstance(prop, dict):
                                continue
                            t = prop.get("type")
                            val: Optional[float] = None
                            if t == "number":
                                val = _prop_number(prop)
                            elif t == "formula":
                                val = _prop_formula_number(prop)
                            elif t == "rollup":
                                val = _prop_rollup_number(prop)
                            if val is None:
                                continue

                            name_out = _truncate_str(
                                str(prop_name_lc), MAX_STRING_LEN
                            ).lower()
                            if name_out in {
                                "period",
                                "week",
                                "cycle",
                                "date",
                                "__numeric__",
                            }:
                                continue
                            numeric.append((name_out, float(val)))

                        for name_out, val in sorted(numeric, key=lambda x: x[0]):
                            if len(out) >= MAX_FIELDS_PER_ROW:
                                truncated = True
                                break
                            out[name_out] = float(val)
                        return

                    prop = _pick_prop(props_lc, list(spec.names or []))
                    if not prop:
                        return

                    t = prop.get("type")
                    kind = spec.kind

                    if kind == "string":
                        val_s = ""
                        if t in {"title", "rich_text"}:
                            val_s = _prop_plain_text(prop)
                        elif t == "select":
                            val_s = _prop_select_name(prop)
                        elif t == "status":
                            val_s = _prop_status_name(prop)
                        if val_s:
                            out[spec.out_key] = _truncate_str(val_s, MAX_STRING_LEN)
                        return

                    if kind == "select":
                        val_s = ""
                        if t == "select":
                            val_s = _prop_select_name(prop)
                        elif t == "status":
                            val_s = _prop_status_name(prop)
                        if val_s:
                            out[spec.out_key] = _truncate_str(val_s, MAX_STRING_LEN)
                        return

                    if kind == "multi_select":
                        if t == "multi_select":
                            arr = _prop_multi_select(prop)
                            if len(arr) > MAX_LIST_LEN:
                                truncated = True
                            out[spec.out_key] = sorted(arr)[:MAX_LIST_LEN]
                        return

                    if kind == "date":
                        if t == "date":
                            dr = _prop_date_range(prop)
                            if isinstance(dr, dict) and dr:
                                out[spec.out_key] = dr
                        return

                    if kind == "people":
                        if t == "people":
                            arr = _prop_people_ids(prop)
                            if len(arr) > MAX_LIST_LEN:
                                truncated = True
                            out[spec.out_key] = arr[:MAX_LIST_LEN]
                        return

                    if kind == "relation":
                        if t == "relation":
                            arr = _prop_relation_ids(prop)
                            if len(arr) > MAX_LIST_LEN:
                                truncated = True
                            out[spec.out_key] = arr[:MAX_LIST_LEN]
                        return

                    if kind == "boolean":
                        if t == "checkbox":
                            b = _prop_checkbox(prop)
                            if b is not None:
                                out[spec.out_key] = bool(b)
                        return

                    if kind == "number":
                        valn: Optional[float] = None
                        if t == "number":
                            valn = _prop_number(prop)
                        elif t == "formula":
                            valn = _prop_formula_number(prop)
                        elif t == "rollup":
                            valn = _prop_rollup_number(prop)
                        if valn is not None:
                            out[spec.out_key] = float(valn)
                        return

                for spec in allow:
                    if len(out) >= MAX_FIELDS_PER_ROW:
                        truncated = True
                        break
                    _add_value(spec)

                return out, bool(truncated)
            except Exception:
                return {}, False

        async def _query_all_pages(
            *, db_key: str, page_size: int = 50, max_items: int = 200
        ) -> List[Dict[str, Any]]:
            out: List[Dict[str, Any]] = []
            cursor: Optional[str] = None
            while True:
                q: Dict[str, Any] = {"page_size": int(page_size)}
                if cursor:
                    q["start_cursor"] = cursor

                res = await self.query_database(db_key=db_key, query=q)
                items = res.get("results") if isinstance(res, dict) else None
                if isinstance(items, list):
                    for it in items:
                        if isinstance(it, dict):
                            out.append(it)
                        if len(out) >= int(max_items):
                            return out

                has_more = res.get("has_more") if isinstance(res, dict) else False
                nxt = res.get("next_cursor") if isinstance(res, dict) else None
                if has_more is True and isinstance(nxt, str) and nxt.strip():
                    cursor = nxt.strip()
                    continue
                return out

        synced_at = _utc_iso()
        payload: Dict[str, Any] = {
            "goals": [],
            "tasks": [],
            "projects": [],
            "databases": {},
            "last_sync": synced_at,
        }
        meta: Dict[str, Any] = {
            "ok": True,
            "synced_at": synced_at,
            "source": "notion",
            "errors": [],
        }

        max_calls = env_int("CEO_NOTION_MAX_CALLS", 3)

        # CEO snapshot latency budget:
        # - per-DB overrides take precedence
        # - then global CEO_NOTION_MAX_LATENCY_MS
        # - then CEO snapshot default (4000ms)
        # NOTE: this does not change error formats or meta schema.
        def _env_int_optional(name: str) -> Optional[int]:
            raw = (os.getenv(name) or "").strip()
            if not raw:
                return None
            try:
                return int(raw)
            except Exception:
                return None

        max_latency_ms_global = _env_int_optional("CEO_NOTION_MAX_LATENCY_MS")
        if max_latency_ms_global is None:
            max_latency_ms_global = 4000

        def _latency_ms_for_db(db_key: str) -> int:
            per_db_env = {
                "goals": "CEO_NOTION_MAX_LATENCY_MS_GOALS",
                "projects": "CEO_NOTION_MAX_LATENCY_MS_PROJECTS",
                "tasks": "CEO_NOTION_MAX_LATENCY_MS_TASKS",
            }.get(db_key)
            if isinstance(per_db_env, str):
                v = _env_int_optional(per_db_env)
                if v is not None:
                    return int(v)
            return int(max_latency_ms_global)

        meta["budget"] = {
            "schema_version": "v1",
            "max_calls": int(max_calls),
            "max_latency_ms": int(max_latency_ms_global),
            "exceeded": False,
            "exceeded_kind": None,
            "exceeded_detail": {},
        }
        meta["notion_calls"] = 0

        db_stats: Dict[str, Any] = {}

        # Default: tasks-first priority (minimum viable context under strict budgets).
        core_order = ["tasks", "projects", "goals"]

        def _normalize_keys(raw: Any) -> List[str]:
            if not isinstance(raw, list):
                return []
            out0: List[str] = []
            seen = set()
            for x in raw:
                s = _ensure_str(x).lower()
                if not s:
                    continue
                if s in seen:
                    continue
                seen.add(s)
                out0.append(s)
            return out0

        keys = _normalize_keys(db_keys)
        if keys:
            # Only keep keys we can resolve.
            keys = [
                k
                for k in keys
                if isinstance(self.db_ids.get(k), str) and self.db_ids.get(k).strip()
            ]
        else:
            keys = list(core_order)

        # For full refresh flows (explicit db_keys passed), keep a stable order:
        # core keys first (if present), then the rest alpha.
        if isinstance(db_keys, list) and db_keys:
            rest = sorted([k for k in keys if k not in set(core_order)])
            keys = [k for k in core_order if k in set(keys)] + rest

        limits = max_items_by_db if isinstance(max_items_by_db, dict) else {}
        default_limits = {"tasks": 50, "projects": 30, "goals": 30}

        # Per-db snapshot sections (new; backward-compatible).
        databases: Dict[str, Any] = {}

        async with notion_budget_context(
            max_calls=max_calls,
            max_latency_ms=int(max_latency_ms_global),
        ) as budget_state:
            for idx, db_key in enumerate(keys):
                try:
                    t_db0 = time.monotonic()
                    # Apply per-DB latency budget *for this db_key*.
                    # Calls budget remains shared across the whole snapshot.
                    try:
                        budget_state.max_latency_ms = int(_latency_ms_for_db(db_key))
                        budget_state.started_at = time.monotonic()
                    except Exception:
                        pass

                    db_id = self._resolve_db_id(db_key)

                    # Production-safe: avoid extra schema network calls.
                    # Title extraction uses page properties fallback when needed.
                    title_prop = "Name"

                    max_items = limits.get(db_key)
                    try:
                        max_items_i = (
                            int(max_items)
                            if max_items is not None
                            else int(default_limits.get(db_key, 50))
                        )
                    except Exception:
                        max_items_i = int(default_limits.get(db_key, 50))
                    if max_items_i <= 0:
                        max_items_i = int(default_limits.get(db_key, 50))

                    # Hard cap for deterministic payload size.
                    if max_items_i > MAX_ITEMS_PER_DB:
                        max_items_i = int(MAX_ITEMS_PER_DB)

                    page_size = min(50, max_items_i)
                    pages = await _query_all_pages(
                        db_key=db_key, page_size=page_size, max_items=max_items_i
                    )

                    items: List[Dict[str, Any]] = []
                    for p in pages:
                        pid = _ensure_str(p.get("id"))
                        title = self._extract_page_title(p, title_prop)
                        # Robust fallback: if schema/title_prop mismatch or title empty,
                        # try any title-typed property present on the page.
                        if not title:
                            props = p.get("properties")
                            if isinstance(props, dict):
                                for prop_name, prop in props.items():
                                    if (
                                        isinstance(prop_name, str)
                                        and isinstance(prop, dict)
                                        and prop.get("type") == "title"
                                    ):
                                        t2 = self._extract_page_title(p, prop_name)
                                        if t2:
                                            title = t2
                                            break
                        url = _ensure_str(p.get("url"))
                        last_edited_time = _ensure_str(p.get("last_edited_time"))
                        created_time = _ensure_str(p.get("created_time"))

                        try:
                            fields, truncated = _extract_allowlisted_fields(db_key, p)
                        except Exception:
                            fields, truncated = {}, False
                        items.append(
                            {
                                "id": pid.replace("-", "") if pid else pid,
                                "notion_id": pid,
                                "title": title,
                                "url": url,
                                "created_time": created_time,
                                "last_edited_time": last_edited_time,
                                "fields": fields,
                                "truncated": bool(truncated),
                            }
                        )

                    payload[db_key] = items
                    db_stats[db_key] = {
                        "ok": True,
                        "db_id": db_id,
                        "title_property": title_prop,
                        "count": int(len(items)),
                        "duration_ms": int(round((time.monotonic() - t_db0) * 1000.0)),
                        "sample_titles": [
                            it.get("title")
                            for it in items[:3]
                            if isinstance(it, dict) and isinstance(it.get("title"), str)
                        ],
                    }

                    databases[db_key] = {
                        "db_id": db_id,
                        "items": items,
                        "row_count": int(len(items)),
                        "last_refreshed_at": synced_at,
                        "last_error": None,
                    }
                except NotionBudgetExceeded as exc:
                    meta["ok"] = False
                    meta["budget"]["exceeded"] = True
                    meta["budget"]["exceeded_kind"] = exc.kind
                    meta["budget"]["exceeded_detail"] = exc.detail
                    try:
                        meta["errors"].append(f"{db_key}:budget_exceeded:{exc.kind}")
                    except Exception:
                        pass
                    payload[db_key] = []
                    db_stats[db_key] = {
                        "ok": False,
                        "error": f"budget_exceeded:{exc.kind}",
                        "budget": exc.detail,
                        "duration_ms": int(round((time.monotonic() - t_db0) * 1000.0)),
                    }

                    databases[db_key] = {
                        "db_id": self.db_ids.get(db_key) or None,
                        "items": [],
                        "row_count": 0,
                        "last_refreshed_at": synced_at,
                        "last_error": {
                            "type": "NotionBudgetExceeded",
                            "message": f"budget_exceeded:{exc.kind}",
                            "at": synced_at,
                            "detail": exc.detail,
                        },
                    }

                    # Deterministic: stop additional calls once budget exceeded.
                    for rest in keys[idx + 1 :]:
                        if rest == db_key:
                            continue
                        db_stats.setdefault(
                            rest,
                            {
                                "ok": False,
                                "error": f"budget_exceeded:{exc.kind}",
                                "budget": exc.detail,
                            },
                        )
                        databases.setdefault(
                            rest,
                            {
                                "db_id": self.db_ids.get(rest) or None,
                                "items": [],
                                "row_count": 0,
                                "last_refreshed_at": synced_at,
                                "last_error": {
                                    "type": "NotionBudgetExceeded",
                                    "message": f"budget_exceeded:{exc.kind}",
                                    "at": synced_at,
                                    "detail": exc.detail,
                                },
                            },
                        )
                    break
                except Exception as exc:  # noqa: BLE001
                    meta["ok"] = False
                    try:
                        meta["errors"].append(
                            f"{db_key}:{type(exc).__name__}:{str(exc)}"
                        )
                    except Exception:
                        pass
                    payload[db_key] = []
                    db_stats[db_key] = {
                        "ok": False,
                        "error": f"{type(exc).__name__}:{str(exc)}",
                        "duration_ms": int(round((time.monotonic() - t_db0) * 1000.0)),
                    }

                    databases[db_key] = {
                        "db_id": self.db_ids.get(db_key) or None,
                        "items": [],
                        "row_count": 0,
                        "last_refreshed_at": synced_at,
                        "last_error": {
                            "type": type(exc).__name__,
                            "message": str(exc),
                            "at": synced_at,
                        },
                    }

            # Export budget stats for downstream trace/grounding_pack
            try:
                meta["notion_calls"] = int(budget_state.calls)
                if budget_state.exceeded and not meta["budget"].get("exceeded"):
                    meta["budget"]["exceeded"] = True
                    meta["budget"]["exceeded_kind"] = budget_state.exceeded_kind
                    meta["budget"]["exceeded_detail"] = budget_state.exceeded_detail
            except Exception:
                pass

        meta["db_stats"] = db_stats
        payload["databases"] = databases
        return {"payload": payload, "meta": meta}

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
                # Support "$op_id" as well as strings that start with "$op_id...".
                m = re.match(r"^\$(?P<id>[A-Za-z0-9_\-]+)(?P<rest>.*)$", v)
                if not m:
                    return v
                key = m.group("id")
                rest = m.group("rest") or ""
                resolved = ref_map.get(key)
                if not resolved:
                    return v
                return f"{resolved}{rest}"
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
                page_url = ""
                if isinstance(sub_res, dict):
                    r = sub_res.get("result")
                    if isinstance(r, dict):
                        page_id = _ensure_str(r.get("page_id") or r.get("id") or "")
                        page_url = _ensure_str(r.get("url") or "")
                if op_id and page_id:
                    ref_map[op_id] = page_id

                results.append(
                    {
                        "index": idx,
                        "op_id": op_id or None,
                        "client_ref": op_id or None,
                        "intent": op_intent,
                        "ok": True,
                        "page_id": page_id or None,
                        "url": page_url or None,
                        "result": sub_res,
                    }
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    {
                        "index": idx,
                        "op_id": op_id or None,
                        "client_ref": op_id or None,
                        "intent": op_intent,
                        "ok": False,
                        "reason": str(exc),
                        "error_type": exc.__class__.__name__,
                    }
                )

        ok_all = all(
            (isinstance(r, dict) and r.get("ok") is True) for r in results
        ) and bool(results)

        # Build a compact, structured summary for UI/clients.
        ops_summary: List[Dict[str, Any]] = []
        for r in results:
            if not isinstance(r, dict):
                continue
            sub = r.get("result") if isinstance(r.get("result"), dict) else {}
            sub_res = sub.get("result") if isinstance(sub.get("result"), dict) else {}
            op_params = None
            try:
                op_params = operations[int(r.get("index"))].get("params")
                if not isinstance(op_params, dict):
                    op_params = operations[int(r.get("index"))].get("payload")
            except Exception:
                op_params = None
            op_params = op_params if isinstance(op_params, dict) else {}

            warnings = None
            if isinstance(sub_res.get("warnings"), list):
                warnings = sub_res.get("warnings")

            ops_summary.append(
                {
                    "index": r.get("index"),
                    "op_id": r.get("op_id"),
                    "action": r.get("intent"),
                    "ok": r.get("ok"),
                    "db_key": sub_res.get("db_key")
                    or op_params.get("db_key")
                    or op_params.get("database"),
                    "page_id": sub_res.get("page_id")
                    or sub_res.get("id")
                    or r.get("page_id"),
                    "url": sub_res.get("url"),
                    "warnings": warnings,
                    "reason": r.get("reason") if r.get("ok") is False else None,
                }
            )
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
                "operations_summary": ops_summary,
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
            # Deterministic targeting fallback: page_id > stable ID property > error.
            page_id = await self._resolve_page_id_for_write_targeting(params)
        if not page_id:
            raise RuntimeError(
                "delete_page requires page_id (or db_key + stable_id_value + stable_id_property)"
            )

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

        warnings: List[str] = []
        build_warnings: List[Dict[str, Any]] = []

        properties = params.get("properties")
        if isinstance(properties, dict) and properties:
            notion_properties = await self._filter_properties_payload_by_schema(
                db_id=db_id, properties=properties, warnings=warnings
            )
        else:
            property_specs = params.get("property_specs")
            if not isinstance(property_specs, dict) or not property_specs:
                raise RuntimeError("create_page requires db_key and properties")
            if isinstance(wrapper_patch, dict) and wrapper_patch:
                try:
                    from services.notion_property_specs_builder import (  # noqa: PLC0415
                        validate_and_build_property_specs,
                    )

                    built = validate_and_build_property_specs(
                        db_key=db_key,
                        property_specs_in=property_specs,
                        wrapper_patch_in=wrapper_patch,
                    )
                    if isinstance(built.get("property_specs"), dict):
                        property_specs = built.get("property_specs")
                    if isinstance(built.get("warnings"), list):
                        build_warnings = [
                            w for w in built.get("warnings") if isinstance(w, dict)
                        ]
                except Exception:
                    build_warnings = []
            notion_properties = await self._build_properties_from_property_specs(
                db_id=db_id, property_specs=property_specs, warnings=warnings
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
                "warnings": warnings,
                "build_warnings": build_warnings,
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

        warnings: List[str] = []
        build_warnings: List[Dict[str, Any]] = []
        if isinstance(wrapper_patch, dict) and wrapper_patch:
            try:
                from services.notion_property_specs_builder import (  # noqa: PLC0415
                    validate_and_build_property_specs,
                )

                built = validate_and_build_property_specs(
                    db_key=db_key,
                    property_specs_in=property_specs,
                    wrapper_patch_in=wrapper_patch,
                )
                if isinstance(built.get("property_specs"), dict):
                    property_specs = built.get("property_specs")
                if isinstance(built.get("warnings"), list):
                    build_warnings = [
                        w for w in built.get("warnings") if isinstance(w, dict)
                    ]
            except Exception:
                build_warnings = []

        # Build Notion properties
        notion_properties = await self._build_properties_from_property_specs(
            db_id=db_id, property_specs=property_specs, warnings=warnings
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
                "warnings": warnings,
                "build_warnings": build_warnings,
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
        build_warnings: List[Dict[str, Any]] = []
        if isinstance(wrapper_patch, dict) and wrapper_patch:
            try:
                from services.notion_property_specs_builder import (  # noqa: PLC0415
                    validate_and_build_property_specs,
                )

                built = validate_and_build_property_specs(
                    db_key=db_key,
                    property_specs_in=property_specs,
                    wrapper_patch_in=wrapper_patch,
                )
                if isinstance(built.get("property_specs"), dict):
                    property_specs = built.get("property_specs")
                if isinstance(built.get("warnings"), list):
                    build_warnings = [
                        w for w in built.get("warnings") if isinstance(w, dict)
                    ]
            except Exception:
                build_warnings = []

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

        if not project_id:
            project_title = _ensure_str(params.get("project_title") or "")
            if project_title:
                rr = await self._resolve_page_id_by_title_best_effort(
                    db_key="projects", title=project_title
                )
                if rr.get("ok") is True and _ensure_str(rr.get("page_id")):
                    project_id = _ensure_str(rr.get("page_id"))
                else:
                    warnings.append(
                        f"project_link_not_resolved:{_ensure_str(rr.get('reason') or '')}"
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
                "build_warnings": build_warnings,
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
        # Use a generic "Name" key; schema-driven normalization will map it to
        # the actual title property (e.g., "Project Name") if needed.
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

        # Collect warnings from property_specs resolution and relation linking
        warnings: List[str] = []
        build_warnings: List[Dict[str, Any]] = []
        if isinstance(wrapper_patch, dict) and wrapper_patch:
            try:
                from services.notion_property_specs_builder import (  # noqa: PLC0415
                    validate_and_build_property_specs,
                )

                built = validate_and_build_property_specs(
                    db_key=db_key,
                    property_specs_in=property_specs,
                    wrapper_patch_in=wrapper_patch,
                )
                if isinstance(built.get("property_specs"), dict):
                    property_specs = built.get("property_specs")
                if isinstance(built.get("warnings"), list):
                    build_warnings = [
                        w for w in built.get("warnings") if isinstance(w, dict)
                    ]
            except Exception:
                build_warnings = []

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
                "build_warnings": build_warnings,
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
            # Deterministic targeting fallback: page_id > stable ID property > error.
            page_id = await self._resolve_page_id_for_write_targeting(params)
        if not page_id:
            raise RuntimeError(
                "update_page requires page_id (or db_key + stable_id_value + stable_id_property)"
            )

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

        warnings: List[str] = []

        wrapper_patch = params.get("wrapper_patch")
        build_warnings: List[Dict[str, Any]] = []
        if isinstance(wrapper_patch, dict) and wrapper_patch and db_key:
            try:
                from services.notion_property_specs_builder import (  # noqa: PLC0415
                    validate_and_build_property_specs,
                )

                built = validate_and_build_property_specs(
                    db_key=db_key,
                    property_specs_in=property_specs,
                    wrapper_patch_in=wrapper_patch,
                )
                if isinstance(built.get("property_specs"), dict):
                    property_specs = built.get("property_specs")
                if isinstance(built.get("warnings"), list):
                    build_warnings = [
                        w for w in built.get("warnings") if isinstance(w, dict)
                    ]
            except Exception:
                build_warnings = []

        # Build Notion properties
        notion_properties: Dict[str, Any] = {}

        raw_props = params.get("properties")
        if isinstance(raw_props, dict) and raw_props and db_id:
            notion_properties = await self._filter_properties_payload_by_schema(
                db_id=db_id, properties=raw_props, warnings=warnings
            )
        elif property_specs and db_id:
            notion_properties = await self._build_properties_from_property_specs(
                db_id=db_id, property_specs=property_specs, warnings=warnings
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
                "warnings": warnings,
                "build_warnings": build_warnings,
            },
            "metadata": metadata,
        }

    async def _resolve_page_id_for_write_targeting(self, params: Dict[str, Any]) -> str:
        """Resolve page_id deterministically when not provided.

        Rule order:
          1) page_id
          2) db_key + stable_id_property + stable_id_value
          3) db_key=tasks + task_id (mapped to stable_id_property=Task ID)
        """
        page_id = _ensure_str(params.get("page_id"))
        if page_id:
            return page_id

        db_key = _ensure_str(params.get("db_key"))
        if not db_key:
            return ""

        stable_prop = _ensure_str(params.get("stable_id_property"))
        stable_val = _ensure_str(
            params.get("stable_id_value")
            or params.get("stable_id")
            or params.get("task_id")
            or ""
        )

        lk = db_key.strip().lower()
        if not stable_prop and lk in {"tasks", "task"} and stable_val:
            stable_prop = "Task ID"

        if not (stable_prop and stable_val):
            return ""

        db_id = self._resolve_db_id(db_key)
        schema = await self._get_database_schema(db_id)
        props = schema.get("properties") if isinstance(schema, dict) else None
        props = props if isinstance(props, dict) else {}

        # Case-insensitive stable_id_property match.
        stable_prop_cf = stable_prop.casefold()
        for k in list(props.keys()):
            if isinstance(k, str) and k.casefold() == stable_prop_cf:
                stable_prop = k
                break

        p = props.get(stable_prop)
        p_type = p.get("type") if isinstance(p, dict) else None
        p_type = p_type.strip() if isinstance(p_type, str) else ""
        if not p_type:
            raise RuntimeError(f"stable_id_property not found in schema: {stable_prop}")

        filt: Dict[str, Any] = {"property": stable_prop}
        if p_type == "rich_text":
            filt["rich_text"] = {"equals": stable_val}
        elif p_type == "title":
            filt["title"] = {"equals": stable_val}
        elif p_type == "number":
            try:
                filt["number"] = {"equals": float(stable_val)}
            except Exception as exc:
                raise RuntimeError(
                    f"stable_id_value not a number: {stable_val}"
                ) from exc
        elif p_type == "select":
            filt["select"] = {"equals": stable_val}
        else:
            raise RuntimeError(
                f"stable_id_property type not supported for targeting: {stable_prop}:{p_type}"
            )

        res = await self.query_database(
            db_key=db_key,
            query={"page_size": 5, "filter": filt},
        )
        items = res.get("results") if isinstance(res, dict) else None
        if not isinstance(items, list) or not items:
            raise RuntimeError(
                f"page not found by stable id: {stable_prop}={stable_val} (db_key={db_key})"
            )

        ids = [_ensure_str(p.get("id")) for p in items if isinstance(p, dict)]
        ids = [x for x in ids if x]

        if len(ids) == 1:
            return ids[0]

        raise RuntimeError(
            f"ambiguous stable id match: {stable_prop}={stable_val} (matches={len(ids)})"
        )

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
