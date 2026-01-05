from __future__ import annotations

import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set

import aiohttp

from services.knowledge_snapshot_service import KnowledgeSnapshotService
from services.notion_schema_registry import NotionSchemaRegistry

NOTION_VERSION_DEFAULT = "2022-06-28"

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class NotionService:
    """
    CANONICAL NOTION SERVICE
    - ČIST EXECUTOR
    - prima AICommand
    - mapira intent → Notion API
    - JEDINA write/read tačka prema Notionu za AI agente

    SNAPSHOT CANON:
    - sync_knowledge_snapshot je READ-only
    - smije čitati više DB-ova (SOP, KPI, leads, plans, itd.)
    - greške po DB/page su non-fatal (boot ne pada)
    """

    def __init__(
        self,
        api_key: Optional[str],
        goals_db_id: Optional[str],
        tasks_db_id: Optional[str],
        projects_db_id: Optional[str],
    ):
        self.api_key = api_key
        self.db_ids: Dict[str, str] = {}

        # 1) Registry (primarni SSOT)
        for key, cfg in NotionSchemaRegistry.DATABASES.items():
            db_id = cfg.get("db_id")
            if db_id:
                self.db_ids[key] = db_id

        # 2) Backward kompatibilnost – eksplicitni parametri imaju prednost
        if goals_db_id:
            self.db_ids["goals"] = goals_db_id
        if tasks_db_id:
            self.db_ids["tasks"] = tasks_db_id
        if projects_db_id:
            self.db_ids["projects"] = projects_db_id

        # 3) Extra iz .env (ENV jači od registry-ja)
        extra_env_map = {
            "active_goals": "NOTION_ACTIVE_GOALS_DB_ID",
            "blocked_goals": "NOTION_BLOCKED_GOALS_DB_ID",
            "completed_goals": "NOTION_COMPLETED_GOALS_DB_ID",
            "agent_exchange": "NOTION_AGENT_EXCHANGE_DB_ID",
            "agent_projects": "NOTION_AGENT_PROJECTS_DB_ID",
            "ai_summary": "NOTION_AI_SUMMARY_DB_ID",
            "ai_weekly_summary": "NOTION_AI_WEEKLY_SUMMARY_DB_ID",
            "flp": "NOTION_FLP_DB_ID",
            "kpi": "NOTION_KPI_DB_ID",
            "lead": "NOTION_LEAD_DB_ID",
            "outreach_sop": "NOTION_OUTREACH_SOP_DB_ID",
            "qualification_sop": "NOTION_QUALIFICATION_SOP_DB_ID",
            "follow_up_sop": "NOTION_FOLLOW_UP_SOP_DB_ID",
            "fsc_sop": "NOTION_FSC_SOP_DB_ID",
            "flp_ops_sop": "NOTION_FLP_OPS_SOP_DB_ID",
            "lss_sop": "NOTION_LSS_SOP_DB_ID",
            "partner_activation_sop": "NOTION_PARTNER_ACTIVATION_SOP_DB_ID",
            "partner_performance_sop": "NOTION_PARTNER_PERFORMANCE_SOP_DB_ID",
            "partner_leadership_sop": "NOTION_PARTNER_LEADERSHIP_SOP_DB_ID",
            "customer_onboarding_sop": "NOTION_CUSTOMER_ONBOARDING_SOP_DB_ID",
            "customer_retention_sop": "NOTION_CUSTOMER_RETENTION_SOP_DB_ID",
            "customer_performance_sop": "NOTION_CUSTOMER_PERFORMANCE_SOP_DB_ID",
            "partner_potential_sop": "NOTION_PARTNER_POTENTIAL_SOP_DB_ID",
            "sales_closing_sop": "NOTION_SALES_CLOSING_SOP_DB_ID",
            "plans": "NOTION_PLANS_DB_ID",
            "sop_master": "NOTION_SOP_MASTER_DB_ID",
        }
        for key, env_name in extra_env_map.items():
            value = os.getenv(env_name)
            if value:
                self.db_ids[key] = value

        # 4) Alias mapiranja
        if "ai_summary" in self.db_ids:
            self.db_ids.setdefault("ai_weekly_summary", self.db_ids["ai_summary"])
        if "lead" in self.db_ids:
            self.db_ids.setdefault("leads", self.db_ids["lead"])

        self.goals_db_id = self.db_ids.get("goals")
        self.tasks_db_id = self.db_ids.get("tasks")
        self.projects_db_id = self.db_ids.get("projects")

        # Property names
        self.goals_status_prop = os.getenv("NOTION_GOALS_STATUS_PROP_NAME", "Status")
        self.goals_priority_prop = os.getenv(
            "NOTION_GOALS_PRIORITY_PROP_NAME", "Priority"
        )
        self.tasks_status_prop = os.getenv("NOTION_TASKS_STATUS_PROP_NAME", "Status")
        self.tasks_priority_prop = os.getenv(
            "NOTION_TASKS_PRIORITY_PROP_NAME", "Priority"
        )

        # Snapshot tuning
        self._snapshot_page_size = int(os.getenv("NOTION_SNAPSHOT_PAGE_SIZE", "50"))
        self._snapshot_compact = os.getenv(
            "NOTION_SNAPSHOT_COMPACT", "true"
        ).lower() in (
            "1",
            "true",
            "yes",
        )
        self._snapshot_include_blocks = os.getenv(
            "NOTION_SNAPSHOT_INCLUDE_BLOCKS", "false"
        ).lower() in ("1", "true", "yes")
        self._snapshot_blocks_page_limit = int(
            os.getenv("NOTION_SNAPSHOT_BLOCKS_PAGE_LIMIT", "5")
        )
        self._snapshot_blocks_per_page_limit = int(
            os.getenv("NOTION_SNAPSHOT_BLOCKS_PER_PAGE_LIMIT", "50")
        )
        self._snapshot_blocks_db_keys = [
            s.strip()
            for s in (os.getenv("NOTION_SNAPSHOT_BLOCKS_DB_KEYS", "")).split(",")
            if s.strip()
        ]

        self._time_management_page_id = os.getenv("NOTION_TIME_MANAGEMENT_PAGE_ID")

        self.session: Optional[aiohttp.ClientSession] = None

        # Log de-dupe (da ne spamuje na svaki reload)
        self._warned_inaccessible: Set[str] = set()
        self._warned_page_fallback: Set[str] = set()

        # In-memory snapshot
        self.knowledge_snapshot: Dict[str, Any] = {
            "last_sync": None,
            "goals": [],
            "tasks": [],
            "projects": [],
            "kpi": [],
            "leads": [],
            "agent_exchange": [],
            "ai_summary": [],
            "goals_summary": None,
            "tasks_summary": None,
            "projects_summary": None,
            "kpi_summary": None,
            "leads_summary": None,
            "agent_exchange_summary": None,
            "extra_databases": {},
            "time_management": None,
            "snapshot_meta": {},
        }

    # --------------------------------------------------
    # SESSION + REQUEST
    # --------------------------------------------------
    async def aclose(self) -> None:
        """Close underlying aiohttp session (called on app shutdown)."""
        if self.session is not None and not self.session.closed:
            await self.session.close()
        self.session = None


    async def _get_session(self) -> aiohttp.ClientSession:
        if not self.api_key:
            raise RuntimeError("NOTION_API_KEY/NOTION_TOKEN missing (NotionService).")

        if self.session is None or self.session.closed:
            notion_version = os.getenv("NOTION_VERSION") or NOTION_VERSION_DEFAULT
            self.session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Notion-Version": notion_version,
                }
            )
        return self.session

    async def _safe_request(
        self,
        method: str,
        url: str,
        payload: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        - POST/PATCH/PUT: payload ide u JSON body
        - GET: payload se NE šalje; koristimo params
        """
        session = await self._get_session()
        kwargs: Dict[str, Any] = {}
        m = method.upper().strip()

        if m in ("POST", "PATCH", "PUT"):
            if payload is not None:
                kwargs["json"] = payload
        else:
            if params:
                kwargs["params"] = params

        async with session.request(m, url, **kwargs) as response:
            text = await response.text()
            if response.status not in (200, 201, 202):
                raise RuntimeError(f"Notion API error {response.status}: {text}")
            return await response.json() if text else {}

    # --------------------------------------------------
    # HELPERS
    # --------------------------------------------------

    def _resolve_db_id(self, db_key: Optional[str], database_id: Optional[str]) -> str:
        if database_id:
            return database_id
        if not db_key:
            raise RuntimeError(
                "Database not specified (db_key or database_id required)."
            )
        if db_key not in self.db_ids:
            raise RuntimeError(f"Unknown db_key '{db_key}' for NotionService.")
        return self.db_ids[db_key]

    def _assert_write_allowed(
        self, *, db_key: Optional[str] = None, database_id: Optional[str] = None
    ) -> None:
        """
        Enforce canonical write_enabled policy from NotionSchemaRegistry if known.
        Unknown DBs are treated as "not enforceable" (backwards-compat), not auto-blocked.
        """
        db_info = None
        db_key_resolved = db_key

        if db_key_resolved:
            try:
                db_info = NotionSchemaRegistry.get_db(db_key_resolved)
            except ValueError:
                db_info = None

        if db_info is None and database_id:
            for key, cfg in NotionSchemaRegistry.DATABASES.items():
                if cfg.get("db_id") == database_id:
                    db_info = cfg
                    db_key_resolved = key
                    break

        if db_info is None:
            return

        if not db_info.get("write_enabled", False):
            raise RuntimeError(
                f"Write operation to Notion DB '{db_key_resolved}' is not allowed by canon (read-only)."
            )

    def _extract_select_name(self, prop: Optional[Dict[str, Any]]) -> Optional[str]:
        if not prop or not isinstance(prop, dict):
            return None

        status = prop.get("status")
        if isinstance(status, dict) and status.get("name"):
            return status["name"]

        select = prop.get("select")
        if isinstance(select, dict) and select.get("name"):
            return select["name"]

        return None

    def _build_status_priority_summary(
        self,
        results: Any,
        status_prop_name: str = "Status",
        priority_prop_name: str = "Priority",
    ) -> Dict[str, Any]:
        by_status: Dict[str, int] = {}
        by_priority: Dict[str, int] = {}

        if not isinstance(results, list):
            return {"total": 0, "by_status": by_status, "by_priority": by_priority}

        for page in results:
            if not isinstance(page, dict):
                continue

            props = page.get("properties") or {}
            status_prop = (
                props.get(status_prop_name)
                or props.get(status_prop_name.upper())
                or props.get(status_prop_name.lower())
            )
            priority_prop = (
                props.get(priority_prop_name)
                or props.get(priority_prop_name.upper())
                or props.get(priority_prop_name.lower())
            )

            status_name = self._extract_select_name(status_prop)
            priority_name = self._extract_select_name(priority_prop)

            if status_name:
                by_status[status_name] = by_status.get(status_name, 0) + 1
            if priority_name:
                by_priority[priority_name] = by_priority.get(priority_name, 0) + 1

        return {
            "total": len(results),
            "by_status": by_status,
            "by_priority": by_priority,
        }

    def _compact_page(self, page: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(page, dict):
            return {"raw": page}

        props = page.get("properties") or {}

        def extract_plain_text(prop: Any) -> Optional[str]:
            if not isinstance(prop, dict):
                return None

            t = prop.get("type")

            if t == "title":
                pieces = prop.get("title") or []
                return "".join(p.get("plain_text", "") for p in pieces).strip() or None

            if t == "rich_text":
                pieces = prop.get("rich_text") or []
                return "".join(p.get("plain_text", "") for p in pieces).strip() or None

            if t == "status":
                v = prop.get("status") or {}
                return v.get("name")

            if t == "select":
                v = prop.get("select") or {}
                return v.get("name")

            if t == "multi_select":
                vals = prop.get("multi_select") or []
                names = [
                    v.get("name") for v in vals if isinstance(v, dict) and v.get("name")
                ]
                return ", ".join(names) if names else None

            if t == "date":
                d = prop.get("date") or {}
                start = d.get("start")
                end = d.get("end")
                if start and end:
                    return f"{start} → {end}"
                return start or end

            if t == "checkbox":
                return str(bool(prop.get("checkbox")))

            if t == "number":
                v = prop.get("number")
                return str(v) if v is not None else None

            if t == "people":
                people = prop.get("people") or []
                names: List[str] = []
                for p in people:
                    if isinstance(p, dict):
                        names.append(p.get("name") or p.get("email") or "")
                names = [n for n in names if n]
                return ", ".join(names) if names else None

            return None

        compact_props: Dict[str, Any] = {}
        for name, prop in props.items():
            val = extract_plain_text(prop)
            if val is not None and val != "":
                compact_props[name] = val

        return {
            "id": page.get("id"),
            "url": page.get("url"),
            "created_time": page.get("created_time"),
            "last_edited_time": page.get("last_edited_time"),
            "properties": compact_props,
        }

    # --------------------------------------------------
    # NOTION ID TYPE DETECTION
    # --------------------------------------------------

    def _looks_like_page_not_db(self, err: str) -> bool:
        return "is a page, not a database" in (err or "").lower()

    def _is_object_not_found(self, err: str) -> bool:
        return (
            "object_not_found" in (err or "").lower()
            or "could not find" in (err or "").lower()
        )

    def _is_no_access(self, err: str) -> bool:
        return (
            "does not contain any data sources accessible by this api bot"
            in (err or "").lower()
        )

    async def _query_db(self, db_id: str, page_size: int) -> List[Dict[str, Any]]:
        resp = await self._safe_request(
            "POST",
            f"https://api.notion.com/v1/databases/{db_id}/query",
            {"page_size": int(page_size)},
        )
        return resp.get("results", []) or []

    async def _retrieve_page(self, page_id: str) -> Dict[str, Any]:
        return await self._safe_request(
            "GET", f"https://api.notion.com/v1/pages/{page_id}"
        )

    async def _retrieve_blocks_limited(
        self, block_id: str, limit: int
    ) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        next_cursor: Optional[str] = None

        lim = int(limit) if limit is not None else 0
        if lim <= 0:
            return results

        while len(results) < lim:
            page_size = min(100, lim - len(results))
            params: Dict[str, Any] = {"page_size": page_size}
            if next_cursor:
                params["start_cursor"] = next_cursor

            url = f"https://api.notion.com/v1/blocks/{block_id}/children"
            data = await self._safe_request("GET", url, params=params)
            batch = data.get("results", []) or []
            results.extend(batch)

            if not data.get("has_more"):
                break

            next_cursor = data.get("next_cursor")
            if not next_cursor:
                break

        return results[:lim]

    # --------------------------------------------------
    # GOAL TEXT PARSER (legacy helper)
    # --------------------------------------------------

    def _parse_goal_command_text(self, text: str):
        if not text:
            return None, None, None, None

        raw = text.strip()
        lower = raw.lower()
        lower_norm = lower.replace("cilj", "goal")

        first_kw_idx = len(raw)
        for kw in ("status", "prioritet", "priority"):
            idx = lower_norm.find(kw)
            if idx != -1 and idx < first_kw_idx:
                first_kw_idx = idx

        name_segment = (
            raw if first_kw_idx == len(raw) else raw[:first_kw_idx].strip(" ,.-")
        )

        patterns = [
            r"(?i)create\s+goal",
            r"(?i)kreiraj\s+goal",
            r"(?i)kreiraj\s+cilj",
            r"(?i)napravi\s+goal",
            r"(?i)napravi\s+cilj",
            r"(?i)postavi\s+goal",
            r"(?i)postavi\s+cilj",
        ]

        goal_name = name_segment
        for pat in patterns:
            goal_name = re.sub(pat, "", goal_name).strip(" :,-")

        if not goal_name:
            goal_name = raw

        status = None
        m_status = re.search(r"(?i)status[: ]+([A-Za-zčćžšđ\s]+)", raw)
        if m_status:
            status = m_status.group(1).strip(" ,.-")

        priority = None
        m_prio = re.search(r"(?i)(prioritet|priority)[: ]+([A-Za-zčćžšđ\s]+)", raw)
        if m_prio:
            priority = m_prio.group(2).strip(" ,.-")

        description = None
        m_sub = re.search(r"(?i)podcilj.*", raw)
        if m_sub:
            description = m_sub.group(0).strip()

        return goal_name, status, priority, description

    # --------------------------------------------------
    # EXECUTION ENTRY POINT
    # --------------------------------------------------

    async def execute(self, command) -> Dict[str, Any]:
        """
        command očekujemo kao AICommand-like: ima intent + params.
        """
        if not getattr(command, "intent", None):
            raise RuntimeError("NotionService called without intent")

        intent = command.intent
        params = command.params or {}

        # ----------------------------
        # LEGACY: create_goal
        # ----------------------------
        if intent == "create_goal":
            if not self.goals_db_id:
                raise RuntimeError("Goals DB not configured (goals_db_id missing).")

            raw_name = params.get("name")
            if not raw_name:
                raise RuntimeError("Missing goal name")

            goal_name, status, priority, description = self._parse_goal_command_text(
                raw_name
            )

            # NOTE:
            # U ovom workspace-u "Status" je SELECT (ne Notion property type "status"),
            # zato MUST šaljemo {"select": {"name": ...}} da izbjegnemo:
            # "Status is expected to be select."
            properties: Dict[str, Any] = {
                "Name": {"title": [{"text": {"content": str(goal_name or raw_name)}}]},
            }

            if status:
                properties[self.goals_status_prop] = {"select": {"name": str(status)}}
            if priority:
                properties[self.goals_priority_prop] = {
                    "select": {"name": str(priority)}
                }
            if description:
                properties["Description"] = {
                    "rich_text": [{"text": {"content": str(description)}}]
                }

            payload = {
                "parent": {"database_id": self.goals_db_id},
                "properties": properties,
            }
            result = await self._safe_request(
                "POST", "https://api.notion.com/v1/pages", payload
            )

            return {
                "success": True,
                "notion_page_id": result.get("id"),
                "notion_url": result.get("url"),
                "url": result.get("url"),
                "database_id": self.goals_db_id,
            }

        # ----------------------------
        # create_page (canonical write)
        # ----------------------------
        if intent == "create_page":
            db_key = params.get("db_key")
            database_id = params.get("database_id")
            property_specs = params.get("property_specs") or {}
            properties = params.get("properties")

            self._assert_write_allowed(db_key=db_key, database_id=database_id)
            db_id = self._resolve_db_id(db_key, database_id)

            if property_specs and not properties:
                properties = self._build_properties_from_specs(property_specs)

            if not properties:
                raise RuntimeError("create_page requires properties or property_specs")

            payload = {"parent": {"database_id": db_id}, "properties": properties}
            result = await self._safe_request(
                "POST", "https://api.notion.com/v1/pages", payload
            )

            return {
                "success": True,
                "notion_page_id": result.get("id"),
                "notion_url": result.get("url"),
                "url": result.get("url"),
                "database_id": db_id,
            }

        # ----------------------------
        # update_page (canonical write)
        # ----------------------------
        if intent == "update_page":
            page_id = params.get("page_id")
            if not page_id:
                raise RuntimeError("update_page requires page_id")

            property_specs = params.get("property_specs") or {}
            properties = params.get("properties")
            db_key = params.get("db_key")
            database_id = params.get("database_id")

            if db_key or database_id:
                self._assert_write_allowed(db_key=db_key, database_id=database_id)

            if property_specs and not properties:
                properties = self._build_properties_from_specs(property_specs)

            if not properties:
                raise RuntimeError("update_page requires properties or property_specs")

            payload = {"properties": properties}
            result = await self._safe_request(
                "PATCH", f"https://api.notion.com/v1/pages/{page_id}", payload
            )

            return {
                "success": True,
                "notion_page_id": result.get("id", page_id),
                "notion_url": result.get("url"),
                "url": result.get("url"),
            }

        # ----------------------------
        # query_database (read)
        # ----------------------------
        if intent == "query_database":
            db_key = params.get("db_key")
            database_id = params.get("database_id")
            db_id = self._resolve_db_id(db_key, database_id)

            filters = params.get("filters")
            sorts = params.get("sorts")
            page_size_raw = params.get("page_size", 50)
            try:
                page_size = int(page_size_raw)
            except Exception:
                page_size = 50

            payload: Dict[str, Any] = {"page_size": page_size}

            if filters:
                if isinstance(filters, dict):
                    payload["filter"] = filters
                elif isinstance(filters, list):
                    if len(filters) == 1:
                        payload["filter"] = filters[0]
                    elif len(filters) > 1:
                        payload["filter"] = {"and": filters}

            if sorts:
                payload["sorts"] = sorts

            url = f"https://api.notion.com/v1/databases/{db_id}/query"
            result = await self._safe_request("POST", url, payload)

            return {
                "success": True,
                "database_id": db_id,
                "results": result.get("results", []),
                "has_more": result.get("has_more", False),
                "next_cursor": result.get("next_cursor"),
            }

        # ----------------------------
        # retrieve_page_content (read)
        # ----------------------------
        if intent == "retrieve_page_content":
            page_id = params.get("page_id")
            if not page_id:
                raise RuntimeError("retrieve_page_content requires page_id")

            page = await self._safe_request(
                "GET", f"https://api.notion.com/v1/pages/{page_id}"
            )
            blocks_resp = await self._safe_request(
                "GET", f"https://api.notion.com/v1/blocks/{page_id}/children"
            )

            return {
                "success": True,
                "page": page,
                "blocks": blocks_resp.get("results", []),
            }

        # ----------------------------
        # refresh_snapshot (read-only)
        # ----------------------------
        if intent == "refresh_snapshot":
            return await self.sync_knowledge_snapshot()

        raise RuntimeError(f"Unsupported intent: {command.intent}")

    # --------------------------------------------------
    # build properties from specs (used by agents)
    # --------------------------------------------------

    def _build_properties_from_specs(
        self, specs: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        props: Dict[str, Any] = {}
        if not specs:
            return props

        for prop_name, spec in specs.items():
            if not isinstance(spec, dict):
                continue

            spec_type = spec.get("type")

            if spec_type == "title":
                text = spec.get("text") or ""
                props[prop_name] = {"title": [{"text": {"content": text}}]}

            elif spec_type == "rich_text":
                text = spec.get("text") or ""
                props[prop_name] = {"rich_text": [{"text": {"content": text}}]}

            elif spec_type == "select":
                name = spec.get("name")
                if name:
                    props[prop_name] = {"select": {"name": name}}

            elif spec_type == "status":
                # COMPAT:
                # U našem Notion setup-u "Status" je često SELECT (ne Notion "status" type).
                # Zato ovdje canonical mapiramo status-spec na select payload.
                name = spec.get("name")
                if name:
                    props[prop_name] = {"select": {"name": name}}

            elif spec_type == "multi_select":
                names = spec.get("names") or []
                props[prop_name] = {"multi_select": [{"name": n} for n in names if n]}

            elif spec_type == "relation":
                page_ids = spec.get("page_ids") or []
                props[prop_name] = {
                    "relation": [{"id": pid} for pid in page_ids if pid]
                }

            elif spec_type == "date":
                start = spec.get("start")
                end = spec.get("end")
                date_payload: Dict[str, Any] = {}
                if start:
                    date_payload["start"] = start
                if end:
                    date_payload["end"] = end
                if date_payload:
                    props[prop_name] = {"date": date_payload}

            elif spec_type == "checkbox":
                props[prop_name] = {"checkbox": bool(spec.get("value"))}

            elif spec_type == "number":
                value = spec.get("value")
                if value is not None:
                    props[prop_name] = {"number": value}

            elif spec_type == "people":
                people = spec.get("people") or spec.get("ids")
                if people is not None:
                    props[prop_name] = {"people": people}

            elif spec_type == "files":
                files = spec.get("files")
                if files:
                    props[prop_name] = {"files": files}

        return props

    # --------------------------------------------------
    # READ-ONLY SNAPSHOT
    # --------------------------------------------------

    async def sync_knowledge_snapshot(self):
        logger.info(">> Syncing Notion knowledge snapshot")

        snapshot: Dict[str, Any] = {
            "last_sync": datetime.utcnow().isoformat(),
            "goals": [],
            "tasks": [],
            "projects": [],
            "kpi": [],
            "leads": [],
            "agent_exchange": [],
            "ai_summary": [],
            "goals_summary": None,
            "tasks_summary": None,
            "projects_summary": None,
            "kpi_summary": None,
            "leads_summary": None,
            "agent_exchange_summary": None,
            "extra_databases": {},
            "time_management": None,
            "snapshot_meta": {
                "page_size": self._snapshot_page_size,
                "compact": self._snapshot_compact,
                "include_blocks": self._snapshot_include_blocks,
                "blocks_db_keys": self._snapshot_blocks_db_keys,
                "blocks_page_limit": self._snapshot_blocks_page_limit,
                "blocks_per_page_limit": self._snapshot_blocks_per_page_limit,
            },
        }

        def maybe_compact(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
            if not self._snapshot_compact:
                return rows
            return [self._compact_page(r) for r in rows]

        goals_results: List[Dict[str, Any]] = []
        tasks_results: List[Dict[str, Any]] = []
        projects_results: List[Dict[str, Any]] = []
        kpi_results: List[Dict[str, Any]] = []
        leads_results: List[Dict[str, Any]] = []
        agent_exchange_results: List[Dict[str, Any]] = []
        ai_summary_results: List[Dict[str, Any]] = []

        # CORE: GOALS
        if self.goals_db_id:
            try:
                goals_results = await self._query_db(
                    self.goals_db_id, self._snapshot_page_size
                )
                snapshot["goals"] = maybe_compact(goals_results)
                snapshot["goals_summary"] = self._build_status_priority_summary(
                    goals_results,
                    status_prop_name=self.goals_status_prop,
                    priority_prop_name=self.goals_priority_prop,
                )
            except Exception as exc:
                logger.info("Failed to sync goals snapshot from Notion: %s", exc)
                snapshot["goals_error"] = str(exc)

        # CORE: TASKS
        if self.tasks_db_id:
            try:
                tasks_results = await self._query_db(
                    self.tasks_db_id, self._snapshot_page_size
                )
                snapshot["tasks"] = maybe_compact(tasks_results)
                snapshot["tasks_summary"] = self._build_status_priority_summary(
                    tasks_results,
                    status_prop_name=self.tasks_status_prop,
                    priority_prop_name=self.tasks_priority_prop,
                )
            except Exception as exc:
                logger.info("Failed to sync tasks snapshot from Notion: %s", exc)
                snapshot["tasks_error"] = str(exc)

        # CORE: PROJECTS
        projects_db_id = self.projects_db_id or self.db_ids.get("projects")
        if projects_db_id:
            try:
                projects_results = await self._query_db(
                    projects_db_id, self._snapshot_page_size
                )
                snapshot["projects"] = maybe_compact(projects_results)
                snapshot["projects_summary"] = self._build_status_priority_summary(
                    projects_results
                )
            except Exception as exc:
                logger.info("Failed to sync projects snapshot from Notion: %s", exc)
                snapshot["projects_error"] = str(exc)

        # CORE: KPI
        kpi_db_id = self.db_ids.get("kpi")
        if kpi_db_id:
            try:
                kpi_results = await self._query_db(kpi_db_id, self._snapshot_page_size)
                snapshot["kpi"] = maybe_compact(kpi_results)
                snapshot["kpi_summary"] = self._build_status_priority_summary(
                    kpi_results
                )
            except Exception as exc:
                logger.info("Failed to sync KPI snapshot from Notion: %s", exc)
                snapshot["kpi_error"] = str(exc)

        # CORE: LEADS
        leads_db_id = self.db_ids.get("leads") or self.db_ids.get("lead")
        if leads_db_id:
            try:
                leads_results = await self._query_db(
                    leads_db_id, self._snapshot_page_size
                )
                snapshot["leads"] = maybe_compact(leads_results)
                snapshot["leads_summary"] = self._build_status_priority_summary(
                    leads_results
                )
            except Exception as exc:
                logger.info(
                    "Failed to sync leads snapshot from Notion (non-fatal): %s", exc
                )
                snapshot["leads_error"] = str(exc)

        # CORE: AGENT EXCHANGE
        agent_exchange_db_id = self.db_ids.get("agent_exchange")
        if agent_exchange_db_id:
            try:
                agent_exchange_results = await self._query_db(
                    agent_exchange_db_id, self._snapshot_page_size
                )
                snapshot["agent_exchange"] = maybe_compact(agent_exchange_results)
                snapshot["agent_exchange_summary"] = (
                    self._build_status_priority_summary(agent_exchange_results)
                )
            except Exception as exc:
                logger.info(
                    "Failed to sync agent_exchange snapshot from Notion: %s", exc
                )
                snapshot["agent_exchange_error"] = str(exc)

        # CORE: AI SUMMARY
        ai_summary_db_id = self.db_ids.get("ai_summary") or self.db_ids.get(
            "ai_weekly_summary"
        )
        if ai_summary_db_id:
            try:
                ai_summary_results = await self._query_db(
                    ai_summary_db_id, self._snapshot_page_size
                )
                snapshot["ai_summary"] = maybe_compact(ai_summary_results)
            except Exception as exc:
                logger.info(
                    "Failed to sync ai_summary snapshot from Notion (non-fatal): %s",
                    exc,
                )
                snapshot["ai_summary_error"] = str(exc)

        # EXTRA: everything else (DB or PAGE)
        core_keys = {
            "goals",
            "tasks",
            "projects",
            "kpi",
            "lead",
            "leads",
            "agent_exchange",
            "ai_summary",
            "ai_weekly_summary",
        }

        for db_key, db_id in self.db_ids.items():
            if db_key in core_keys:
                continue

            # 1) pokušaj kao DB
            try:
                rows = await self._query_db(db_id, self._snapshot_page_size)
                snapshot["extra_databases"][db_key] = maybe_compact(rows)

                # blocks (samo ako je DB i traženo)
                if (
                    self._snapshot_include_blocks
                    and db_key in self._snapshot_blocks_db_keys
                ):
                    pages = rows[: self._snapshot_blocks_page_limit]
                    blocks_map: Dict[str, Any] = {}
                    for p in pages:
                        pid = p.get("id") if isinstance(p, dict) else None
                        if not pid:
                            continue
                        try:
                            blocks = await self._retrieve_blocks_limited(
                                pid, self._snapshot_blocks_per_page_limit
                            )
                            blocks_map[pid] = blocks
                        except Exception as exc:
                            blocks_map[pid] = {"error": str(exc)}
                    snapshot["extra_databases"][f"{db_key}__blocks"] = blocks_map

                continue

            except Exception as exc:
                msg = str(exc)

                # 2) DB configured but is PAGE -> fallback on page read
                if self._looks_like_page_not_db(msg):
                    if db_key not in self._warned_page_fallback:
                        self._warned_page_fallback.add(db_key)
                        logger.info(
                            "Notion source '%s' configured as DB but is a PAGE. Falling back to page read.",
                            db_key,
                        )
                    try:
                        page = await self._retrieve_page(db_id)
                        blocks = None
                        if (
                            self._snapshot_include_blocks
                            and db_key in self._snapshot_blocks_db_keys
                        ):
                            blocks = await self._retrieve_blocks_limited(
                                db_id, self._snapshot_blocks_per_page_limit
                            )
                        snapshot["extra_databases"][db_key] = {
                            "kind": "page",
                            "page": self._compact_page(page)
                            if self._snapshot_compact
                            else page,
                            "blocks": blocks,
                        }
                    except Exception as exc2:
                        snapshot["extra_databases"][f"{db_key}__error"] = str(exc2)

                    if db_key not in self._warned_inaccessible:
                        self._warned_inaccessible.add(db_key)
                        logger.info(
                            "Notion source '%s' not accessible (share DB/page with integration). key=%s",
                            db_key,
                            db_key,
                        )
                    continue

                # 3) Not accessible (permissions / not found)
                if self._is_no_access(msg) or self._is_object_not_found(msg):
                    snapshot["extra_databases"][f"{db_key}__error"] = msg
                    if db_key not in self._warned_inaccessible:
                        self._warned_inaccessible.add(db_key)
                        logger.info(
                            "Notion source '%s' not accessible (share DB/page with integration). key=%s",
                            db_key,
                            db_key,
                        )
                    continue

                # 4) Other unexpected error
                snapshot["extra_databases"][f"{db_key}__error"] = msg
                logger.info("Failed to sync db_key='%s' from Notion: %s", db_key, msg)

        # TIME MANAGEMENT PAGE (optional)
        if self._time_management_page_id:
            try:
                page = await self._retrieve_page(self._time_management_page_id)
                blocks = None
                if self._snapshot_include_blocks:
                    blocks = await self._retrieve_blocks_limited(
                        self._time_management_page_id,
                        self._snapshot_blocks_per_page_limit,
                    )
                snapshot["time_management"] = {
                    "page": self._compact_page(page)
                    if self._snapshot_compact
                    else page,
                    "blocks": blocks,
                }
            except Exception as exc:
                logger.info("Failed to sync Time Management page (non-fatal): %s", exc)
                snapshot["time_management_error"] = str(exc)

        self.knowledge_snapshot = snapshot
        KnowledgeSnapshotService.update_snapshot(snapshot)

        logger.info(
            ">> Notion knowledge snapshot synced "
            f"(goals={len(goals_results)}, tasks={len(tasks_results)}, "
            f"projects={len(projects_results)}, kpi={len(kpi_results)}, "
            f"leads={len(leads_results)}, agent_exchange={len(agent_exchange_results)}, "
            f"ai_summary={len(ai_summary_results)}, extra_db={len(snapshot['extra_databases'])})"
        )

        return {
            "ok": True,
            "last_sync": snapshot["last_sync"],
            "total_goals": len(goals_results),
            "total_tasks": len(tasks_results),
            "total_projects": len(projects_results),
            "total_kpi": len(kpi_results),
            "total_leads": len(leads_results),
            "total_agent_exchange": len(agent_exchange_results),
            "total_ai_summary": len(ai_summary_results),
            "extra_databases_keys": list(snapshot["extra_databases"].keys()),
            "time_management_loaded": bool(snapshot.get("time_management")),
        }

    def get_knowledge_snapshot(self) -> Dict[str, Any]:
        return dict(self.knowledge_snapshot)

    # --------------------------------------------------
    # SHUTDOWN (close aiohttp session)
    # --------------------------------------------------

    async def aclose(self) -> None:
        """
        Graceful shutdown for aiohttp session.
        Eliminates: 'Unclosed client session' / 'Unclosed connector' on Ctrl+C / reload.
        """
        sess = self.session
        self.session = None
        if sess is not None and not sess.closed:
            try:
                await sess.close()
            except Exception:
                # fail-soft: shutdown path must not raise
                pass


# --------------------------------------------------
# SINGLETON (KANONSKI)
# --------------------------------------------------

_NOTION_SERVICE_SINGLETON: Optional[NotionService] = None


def set_notion_service(service: NotionService) -> None:
    global _NOTION_SERVICE_SINGLETON
    _NOTION_SERVICE_SINGLETON = service


def get_notion_service() -> NotionService:
    if _NOTION_SERVICE_SINGLETON is None:
        raise RuntimeError("NotionService not initialized")
    return _NOTION_SERVICE_SINGLETON
