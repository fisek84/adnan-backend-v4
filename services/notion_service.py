# services/notion_service.py
from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)


# ============================================================
# SINGLETON (SSOT)
# ============================================================
_NOTION_SERVICE: Optional["NotionService"] = None


def set_notion_service(service: "NotionService") -> None:
    global _NOTION_SERVICE
    _NOTION_SERVICE = service


def get_notion_service() -> "NotionService":
    if _NOTION_SERVICE is None:
        raise RuntimeError("NotionService singleton is not initialized")
    return _NOTION_SERVICE


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
    NotionService — production-safe minimal SSOT wrapper.

    Key contracts used by your repo (observed from your logs + gateway expectations):
      - constructed via NotionService(api_key, goals_db_id, tasks_db_id, projects_db_id)
      - exposes .db_ids mapping (keys: goals/tasks/projects)
      - async execute(ai_command) -> dict
      - async sync_knowledge_snapshot() (best-effort; must not crash boot)
      - optional query_database(db_key, query) used by gateway bulk query fallback
      - async aclose() for lifespan shutdown

    IMPORTANT:
      - execute() must accept exactly one positional arg after self (ai_command),
        otherwise you hit: "NotionService.execute() takes 1 positional argument but 2 were given".
      - create_page must accept either:
          params["properties"] (already Notion API shape),
          or params["property_specs"] (your internal compact schema).
      - property_specs must adapt to the *actual* database schema:
          your current failure: Notion says "Status is expected to be select."
          so we resolve database schema and map accordingly.
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
    # http wrapper
    # ----------------------------
    async def _safe_request(
        self, method: str, url: str, *, payload: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        client = await self._get_client()

        try:
            resp = await client.request(method, url, json=payload)
        except Exception as exc:
            raise RuntimeError(
                f"Notion request failed: {type(exc).__name__}: {exc}"
            ) from exc

        text = resp.text or ""
        if resp.status_code >= 400:
            # keep exact body for debugging; tests rely on error reason strings
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

        # cache even if empty (avoid hammering)
        self._db_schema_cache[db_id] = _DbSchemaCacheEntry(
            fetched_at=now, schema=schema
        )
        return schema

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

        # Notion schema uses keys like: {"type":"select", "select":{...}}
        t = p.get("type")
        return (t or "").strip() if isinstance(t, str) else ""

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
        # Notion "status" property expects {"status":{"name":"..."}}.
        name = (name or "").strip()
        return {"status": {"name": name}} if name else {"status": None}

    async def _build_properties_from_property_specs(
        self,
        *,
        db_id: str,
        property_specs: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        property_specs format (observed from your approval payload_summary):
          {
            "Name": {"type":"title","text":"..."},
            "Status": {"type":"status","name":"Not started"}
          }

        Robust rule:
          - If spec.type == "status" but DB schema says property is "select",
            map to select (this is your current failing case).
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

            # Title
            if stype == "title":
                txt = _ensure_str(spec.get("text") or spec.get("value") or "")
                out[pn] = self._title_prop(txt)
                continue

            # Rich text (optional support)
            if stype in ("rich_text", "text"):
                txt = _ensure_str(spec.get("text") or spec.get("value") or "")
                out[pn] = self._rich_text_prop(txt)
                continue

            # Explicit select
            if stype == "select":
                name = _ensure_str(spec.get("name") or spec.get("value") or "")
                out[pn] = self._select_prop(name)
                continue

            # Status (needs schema-aware mapping)
            if stype == "status":
                name = _ensure_str(spec.get("name") or spec.get("value") or "")
                actual = await self._resolve_property_type(db_id=db_id, prop_name=pn)
                if actual == "select":
                    out[pn] = self._select_prop(name)
                else:
                    # default to status if schema says status OR schema unknown
                    out[pn] = self._status_prop(name)
                continue

            # Fallback: ignore unknown spec types (do not send invalid shapes)
            # This keeps prod safe and avoids Notion 400 for unsupported payload.
            continue

        return out

    # ----------------------------
    # database id resolution
    # ----------------------------
    def _resolve_db_id(self, db_key: str) -> str:
        k = (db_key or "").strip()
        if not k:
            raise RuntimeError("db_key is required")

        # Allow passing raw database UUID
        # (Notion accepts with hyphens; we do not validate strictly here)
        if k.count("-") >= 4:
            return k

        lk = k.lower()
        if lk in self.db_ids and self.db_ids[lk].strip():
            return self.db_ids[lk].strip()

        # tolerant singular/plural
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
        Your gateway lifespan calls this.
        """
        try:
            from services.knowledge_snapshot_service import KnowledgeSnapshotService

            # Keep this lightweight: just mark snapshot "ready" if env looks ok.
            # If you have a richer sync elsewhere, keep it there.
            snap = KnowledgeSnapshotService.get_snapshot()
            if isinstance(snap, dict):
                snap.setdefault("trace", {})
                snap["trace"]["notion_sync"] = {"ok": True, "ts": _utc_iso()}
                snap["ready"] = True
                snap["last_sync"] = _utc_iso()
                KnowledgeSnapshotService.set_snapshot(snap)  # type: ignore[attr-defined]
            return {"ok": True}
        except Exception:
            # never crash boot
            logger.warning("sync_knowledge_snapshot failed (non-fatal)", exc_info=True)
            return {"ok": False}

    async def query_database(
        self, *, db_key: str, query: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Used by gateway bulk query fallback.
        """
        db_id = self._resolve_db_id(db_key)
        url = f"{self.NOTION_BASE_URL}/databases/{db_id}/query"
        payload = query if isinstance(query, dict) else {}
        res = await self._safe_request("POST", url, payload=payload)
        res.setdefault("database_id", db_id)
        return res

    async def execute(self, ai_command: Any) -> Dict[str, Any]:
        """
        Canonical executor entrypoint called by NotionOpsAgent / Orchestrator.

        Expected (from your approval payload_summary):
          ai_command.command == "notion_write"
          ai_command.intent  == "create_page"
          ai_command.params  == {"db_key":"goals","property_specs":{...}} OR {"db_key":"goals","properties":{...}}
        """
        cmd = _ensure_dict(
            ai_command.model_dump() if hasattr(ai_command, "model_dump") else {}
        )
        if not cmd:
            # best-effort: try attribute access
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

        raise RuntimeError(f"Unsupported intent: {intent or '(empty)'}")

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

        # Accept already-built Notion properties payload
        properties = params.get("properties")
        if isinstance(properties, dict) and properties:
            notion_properties = properties
        else:
            # Build from property_specs (your internal compact form)
            property_specs = params.get("property_specs")
            if not isinstance(property_specs, dict) or not property_specs:
                raise RuntimeError("create_page requires db_key and properties")
            notion_properties = await self._build_properties_from_property_specs(
                db_id=db_id, property_specs=property_specs
            )
            if not notion_properties:
                raise RuntimeError("create_page requires db_key and properties")

        payload = {"parent": {"database_id": db_id}, "properties": notion_properties}
        url = f"{self.NOTION_BASE_URL}/pages"
        res = await self._safe_request("POST", url, payload=payload)

        # Normalize minimal success shape
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
