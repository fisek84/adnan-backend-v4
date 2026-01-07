from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Union

import aiohttp

from services.knowledge_snapshot_service import KnowledgeSnapshotService
from services.notion_schema_registry import NotionSchemaRegistry

NOTION_VERSION_DEFAULT = "2022-06-28"
LAST_CREATED_GOAL_TOKEN = "LAST_CREATED_GOAL"

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

    # ✅ Derived view DBs are OPTIONAL: if integration has no access / object not found,
    # we do NOT want to poison snapshot with __error keys (tests expect clean snapshot).
    _SOFT_DERIVED_VIEW_KEYS: Set[str] = {
        "active_goals",
        "blocked_goals",
        "completed_goals",
    }

    # ✅ Everything except the core operational DBs is treated as "soft optional" for snapshot.
    # If Notion integration doesn't have access / object missing, snapshot should not accumulate errors.
    _SNAPSHOT_HARD_REQUIRED_KEYS: Set[str] = {
        "goals",
        "tasks",
        "projects",
    }

    def __init__(
        self,
        api_key: Optional[str],
        goals_db_id: Optional[str],
        tasks_db_id: Optional[str],
        projects_db_id: Optional[str],
    ):
        self.api_key = (api_key or "").strip() or None
        self.db_ids: Dict[str, str] = {}

        # 1) Registry (primarni SSOT)
        for key, cfg in NotionSchemaRegistry.DATABASES.items():
            db_id = cfg.get("db_id")
            if db_id:
                self.db_ids[str(key).strip().lower()] = str(db_id).strip()

        # 2) Backward kompatibilnost – eksplicitni parametri imaju prednost
        if goals_db_id:
            self.db_ids["goals"] = str(goals_db_id).strip()
        if tasks_db_id:
            self.db_ids["tasks"] = str(tasks_db_id).strip()
        if projects_db_id:
            self.db_ids["projects"] = str(projects_db_id).strip()

        # 3) Extra iz .env (legacy map; ostaje radi kompatibilnosti)
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
            value = (os.getenv(env_name) or "").strip()
            if value:
                self.db_ids[str(key).strip().lower()] = value

        # 4) AUTOMATSKI: pokupi SVE NOTION_*_DB_ID iz env-a (ENV je najsnažniji SSOT)
        self._ingest_all_env_db_ids()

        # 5) Alias mapiranja (kompatibilnost)
        # ✅ FIX: enforce a SINGLE canonical ID for ai_summary/ai_weekly_summary.
        # If both exist and differ, prefer ai_summary (workflow uses db_key="ai_summary")
        if "ai_summary" in self.db_ids and "ai_weekly_summary" in self.db_ids:
            if self.db_ids["ai_summary"] != self.db_ids["ai_weekly_summary"]:
                logger.warning(
                    "NotionService: ai_summary (%s) and ai_weekly_summary (%s) differ; "
                    "forcing ai_weekly_summary to ai_summary.",
                    self.db_ids["ai_summary"],
                    self.db_ids["ai_weekly_summary"],
                )
            self.db_ids["ai_weekly_summary"] = self.db_ids["ai_summary"]
        elif "ai_summary" in self.db_ids:
            self.db_ids["ai_weekly_summary"] = self.db_ids["ai_summary"]
        elif "ai_weekly_summary" in self.db_ids:
            self.db_ids["ai_summary"] = self.db_ids["ai_weekly_summary"]

        if "lead" in self.db_ids:
            self.db_ids.setdefault("leads", self.db_ids["lead"])
        if "leads" in self.db_ids:
            self.db_ids.setdefault("lead", self.db_ids["leads"])

        # Canonical shortcuts (ostaju jer drugi dijelovi sistema ovo očekuju)
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
        ).lower() in (
            "1",
            "true",
            "yes",
        )
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
        self._warned_alias_conflict: Set[str] = set()

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

    def _ingest_all_env_db_ids(self) -> None:
        """
        Skenira env za sve varijable formata:
          NOTION_<SOMETHING>_DB_ID=<id>
        i mapira u:
          db_ids["<something_lower_snake>"] = <id>

        Primjer:
          NOTION_CUSTOMER_PERFORMANCE_SOP_DB_ID -> key "customer_performance_sop"
        """
        for env_name, raw_val in os.environ.items():
            if not env_name.startswith("NOTION_"):
                continue
            if not env_name.endswith("_DB_ID"):
                continue

            val = (raw_val or "").strip()
            if not val:
                continue

            mid = env_name[len("NOTION_") : -len("_DB_ID")]
            key = mid.strip().lower()
            key = re.sub(r"\s+", "_", key)
            key = re.sub(r"_+", "_", key).strip("_")

            if not key:
                continue

            # ENV je “final authority”
            self.db_ids[key] = val

    # --------------------------------------------------
    # SESSION + REQUEST
    # --------------------------------------------------

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

        Production note:
        - body čitamo jednom kao bytes i dekodiramo kao UTF-8 (error tekst i JSON)
        - izbjegavamo dvostruko čitanje response body-a
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
            body = await response.read()
            text = body.decode("utf-8", errors="replace") if body else ""

            if response.status not in (200, 201, 202):
                raise RuntimeError(f"Notion API error {response.status}: {text}")

            if not text.strip():
                return {}

            try:
                parsed = json.loads(text)
            except Exception as exc:
                raise RuntimeError(f"Notion API returned non-JSON body: {exc}: {text}")

            return parsed if isinstance(parsed, dict) else {"raw": parsed}

    # --------------------------------------------------
    # HELPERS
    # --------------------------------------------------

    def _normalize_db_key(self, db_key: Optional[str]) -> Optional[str]:
        if not isinstance(db_key, str):
            return None
        k = db_key.strip().lower()
        if not k:
            return None
        k = re.sub(r"\s+", "_", k)
        k = re.sub(r"_+", "_", k).strip("_")
        return k or None

    def _resolve_db_id(self, db_key: Optional[str], database_id: Optional[str]) -> str:
        if database_id:
            return str(database_id).strip()

        k = self._normalize_db_key(db_key)
        if not k:
            raise RuntimeError(
                "Database not specified (db_key or database_id required)."
            )

        # direktno
        if k in self.db_ids:
            return self.db_ids[k]

        # probaj singular/plural fallback
        if k.endswith("s") and k[:-1] in self.db_ids:
            return self.db_ids[k[:-1]]
        if (k + "s") in self.db_ids:
            return self.db_ids[k + "s"]

        raise RuntimeError(f"Unknown db_key '{db_key}' for NotionService.")

    def _assert_write_allowed(
        self, *, db_key: Optional[str] = None, database_id: Optional[str] = None
    ) -> None:
        """
        Enforce canonical write_enabled policy from NotionSchemaRegistry if known.
        Unknown DBs are treated as "not enforceable" (backwards-compat), not auto-blocked.
        """
        db_info = None
        db_key_resolved = self._normalize_db_key(db_key) if db_key else None

        if db_key_resolved:
            try:
                db_info = NotionSchemaRegistry.get_db(db_key_resolved)
            except ValueError:
                db_info = None

        if db_info is None and database_id:
            for key, cfg in NotionSchemaRegistry.DATABASES.items():
                if cfg.get("db_id") == database_id:
                    db_info = cfg
                    db_key_resolved = str(key)
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
            return select.get("name")

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

    def _extract_page_title(self, page: Dict[str, Any]) -> str:
        if not isinstance(page, dict):
            return ""

        props = page.get("properties") or {}
        if not isinstance(props, dict):
            return ""

        for prop in props.values():
            if not isinstance(prop, dict):
                continue
            if prop.get("type") != "title":
                continue
            title_items = prop.get("title") or []
            if not isinstance(title_items, list):
                return ""
            return "".join((t.get("plain_text", "") or "") for t in title_items).strip()

        return ""

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

    def _is_soft_optional_snapshot_key(self, key: str) -> bool:
        k = self._normalize_db_key(key) or key
        if k in self._SNAPSHOT_HARD_REQUIRED_KEYS:
            return False
        return True

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
    # WRAPPER UNWRAP (NEW) + BATCH SUPPORT
    # --------------------------------------------------

    def _unwrap_ai_command(
        self, params: Dict[str, Any]
    ) -> Optional[Union[Dict[str, Any], List[Dict[str, Any]]]]:
        """
        Supports payload shapes:
          params = {"ai_command": {...}}  # dict
          params = {"ai_command": AICommandLike}  # object with intent/params
          params = {"ai_commands": [{...}, {...}]}  # list (preferred)
          params = {"ai_command": [{...}, {...}]}   # list (alias)
        Returns:
          - dict: {"intent": str, "params": dict}
          - or list[dict] with the same shape (batch)
        """
        if not isinstance(params, dict):
            return None

        # Batch support first
        ai_list = params.get("ai_commands")
        if not isinstance(ai_list, list):
            ai_list = (
                params.get("ai_command")
                if isinstance(params.get("ai_command"), list)
                else None
            )

        if isinstance(ai_list, list):
            out: List[Dict[str, Any]] = []
            for it in ai_list:
                if isinstance(it, dict):
                    inner_intent = it.get("intent")
                    inner_params = it.get("params")
                    if isinstance(inner_intent, str) and isinstance(inner_params, dict):
                        out.append({"intent": inner_intent, "params": inner_params})
                    continue

                inner_intent = getattr(it, "intent", None)
                inner_params = getattr(it, "params", None)
                if isinstance(inner_intent, str) and isinstance(inner_params, dict):
                    out.append({"intent": inner_intent, "params": inner_params})

            return out if out else None

        # Single support
        ai = params.get("ai_command")
        if ai is None:
            return None

        if isinstance(ai, dict):
            inner_intent = ai.get("intent")
            inner_params = ai.get("params")
            if isinstance(inner_intent, str) and isinstance(inner_params, dict):
                return {"intent": inner_intent, "params": inner_params}
            return None

        inner_intent = getattr(ai, "intent", None)
        inner_params = getattr(ai, "params", None)
        if isinstance(inner_intent, str) and isinstance(inner_params, dict):
            return {"intent": inner_intent, "params": inner_params}

        return None

    def _property_specs_has_last_created_goal_placeholder(self, specs: Any) -> bool:
        if not isinstance(specs, dict):
            return False
        spec = specs.get("Goal")
        if not isinstance(spec, dict):
            return False
        if spec.get("type") != "relation":
            return False
        return spec.get("related_to") == LAST_CREATED_GOAL_TOKEN

    def _substitute_last_created_goal_placeholder(
        self, specs: Dict[str, Any], *, last_goal_id: str
    ) -> Dict[str, Any]:
        """
        Replaces:
          "Goal": { "type":"relation", "related_to":"LAST_CREATED_GOAL" }
        with:
          "Goal": { "type":"relation", "page_ids":[<last_goal_id>] }
        """
        if not isinstance(specs, dict):
            return {}
        out: Dict[str, Any] = dict(specs)
        spec = out.get("Goal")
        if (
            isinstance(spec, dict)
            and spec.get("type") == "relation"
            and spec.get("related_to") == LAST_CREATED_GOAL_TOKEN
        ):
            out["Goal"] = {"type": "relation", "page_ids": [last_goal_id]}
        return out

    def _is_goal_create_command(
        self, *, intent: str, params: Dict[str, Any], result: Any
    ) -> bool:
        # Accept legacy goal intent too, for robustness
        if intent == "create_goal":
            return True

        if intent != "create_page":
            return False
        if not isinstance(params, dict):
            return False

        db_key = params.get("db_key")
        if isinstance(db_key, str) and self._normalize_db_key(db_key) == "goals":
            return True

        database_id = params.get("database_id")
        if (
            isinstance(database_id, str)
            and self.goals_db_id
            and database_id.strip() == str(self.goals_db_id).strip()
        ):
            return True

        if isinstance(result, dict):
            rid = result.get("database_id")
            if (
                isinstance(rid, str)
                and self.goals_db_id
                and rid.strip() == str(self.goals_db_id).strip()
            ):
                return True

        return False

    async def _execute_batch_ai_commands(
        self, ai_commands: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Executes list of inner ai_commands sequentially.
        Tracks last_created_goal_id and substitutes LAST_CREATED_GOAL in subsequent commands.
        If no goal exists and a task asks for LAST_CREATED_GOAL: returns a per-item failure and continues.
        """

        class _CmdShim:
            def __init__(self, intent: str, params: Dict[str, Any]) -> None:
                self.intent = intent
                self.params = params

        results: List[Dict[str, Any]] = []
        last_created_goal_id: Optional[str] = None
        had_failures = False

        for idx, item in enumerate(ai_commands, start=1):
            intent = item.get("intent")
            params = item.get("params")

            if (
                not isinstance(intent, str)
                or not intent.strip()
                or not isinstance(params, dict)
            ):
                had_failures = True
                results.append(
                    {
                        "index": idx,
                        "success": False,
                        "reason": "invalid_ai_command_shape",
                        "ai_command": item,
                    }
                )
                continue

            substituted = False
            prop_specs = params.get("property_specs")

            if isinstance(
                prop_specs, dict
            ) and self._property_specs_has_last_created_goal_placeholder(prop_specs):
                if isinstance(last_created_goal_id, str) and last_created_goal_id:
                    params = dict(params)
                    params["property_specs"] = (
                        self._substitute_last_created_goal_placeholder(
                            prop_specs, last_goal_id=last_created_goal_id
                        )
                    )
                    substituted = True
                else:
                    had_failures = True
                    logger.warning(
                        "Batch execution: missing last_created_goal_id for LAST_CREATED_GOAL placeholder (index=%s).",
                        idx,
                    )
                    results.append(
                        {
                            "index": idx,
                            "success": False,
                            "reason": "missing_last_created_goal_id_for_relation",
                            "placeholder": LAST_CREATED_GOAL_TOKEN,
                        }
                    )
                    continue

            try:
                res = await self.execute(_CmdShim(intent=intent, params=params))
            except Exception as exc:
                had_failures = True
                logger.exception(
                    "Batch execution failed (index=%s intent=%s)", idx, intent
                )
                results.append(
                    {
                        "index": idx,
                        "success": False,
                        "reason": str(exc),
                        "error_type": exc.__class__.__name__,
                    }
                )
                continue

            if self._is_goal_create_command(intent=intent, params=params, result=res):
                pid = res.get("notion_page_id") if isinstance(res, dict) else None
                if isinstance(pid, str) and pid:
                    last_created_goal_id = pid

            ok = True
            if isinstance(res, dict) and (
                res.get("success") is False or res.get("ok") is False
            ):
                ok = False
                had_failures = True

            results.append(
                {
                    "index": idx,
                    "success": ok,
                    "intent": intent,
                    "substituted_last_created_goal": substituted,
                    "result": res,
                }
            )

        return {
            "success": True,
            "batch": True,
            "had_failures": had_failures,
            "last_created_goal_id": last_created_goal_id,
            "results": results,
        }

    # --------------------------------------------------
    # EXECUTION ENTRY POINT
    # --------------------------------------------------

    async def execute(self, command) -> Dict[str, Any]:
        """
        command očekujemo kao AICommand-like: ima intent + params.

        IMPORTANT:
        - orchestrator/UI često šalje wrapper intent: "notion_write"/"notion_read"
          a stvarni Notion intent je u params.ai_command.intent.
        """
        if not getattr(command, "intent", None):
            raise RuntimeError("NotionService called without intent")

        intent = command.intent
        params = command.params or {}

        # unwrap outer envelope
        if intent in ("notion_write", "notion_read"):
            unwrapped = self._unwrap_ai_command(
                params if isinstance(params, dict) else {}
            )
            if not unwrapped:
                raise RuntimeError(
                    "notion_write/notion_read requires params.ai_command (or ai_commands) with inner intent/params"
                )

            if isinstance(unwrapped, list):
                return await self._execute_batch_ai_commands(unwrapped)

            intent = unwrapped["intent"]
            params = unwrapped["params"]

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
        # ✅ READ: read page -> markdown (NO FALLBACK TO RANDOM PAGE)
        # ----------------------------
        if intent == "read_page_as_markdown":
            query = params.get("query")
            if not isinstance(query, str) or not query.strip():
                raise RuntimeError(
                    "read_page_as_markdown requires params.query (non-empty string)"
                )

            # local import to avoid circular import at module import-time
            from services.notion_read_service import NotionReadService

            svc = NotionReadService(self)
            page = await svc.get_page_by_title_contains(query.strip())

            # ✅ If no title contains match -> return empty
            if not page:
                return {"success": True, "title": "", "url": "", "content_markdown": ""}

            title = self._extract_page_title(page)
            url = page.get("url") or ""
            content_md = await svc.render_page_to_markdown(page)

            return {
                "success": True,
                "title": title,
                "url": url,
                "content_markdown": content_md or "",
            }

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

        if intent == "refresh_snapshot":
            return await self.sync_knowledge_snapshot()

        raise RuntimeError(f"Unsupported intent: {intent}")

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
                name = spec.get("name")
                if name:
                    # DB-ovi često imaju "Status" kao SELECT, ne notion status-type.
                    props[prop_name] = {"select": {"name": name}}

            elif spec_type == "multi_select":
                names = spec.get("names") or []
                props[prop_name] = {"multi_select": [{"name": n} for n in names if n]}

            elif spec_type == "relation":
                page_ids = spec.get("page_ids") or spec.get("ids") or []
                if not isinstance(page_ids, list):
                    page_ids = []
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
                people = spec.get("people") or spec.get("ids") or []
                norm: List[Dict[str, Any]] = []
                if isinstance(people, list):
                    for p in people:
                        if isinstance(p, str) and p.strip():
                            norm.append({"id": p.strip()})
                        elif isinstance(p, dict):
                            pid = p.get("id")
                            if isinstance(pid, str) and pid.strip():
                                norm.append({"id": pid.strip()})
                if norm:
                    props[prop_name] = {"people": norm}

            elif spec_type == "files":
                files = spec.get("files")
                if files:
                    props[prop_name] = {"files": files}

        return props

    # --------------------------------------------------
    # SNAPSHOT (READ-ONLY)
    # --------------------------------------------------

    async def build_knowledge_snapshot(self) -> Dict[str, Any]:
        """
        Read-only: queries configured Notion DBs and produces a stable wrapper:
          {
            "payload": { ... },
            "meta": { "ok": bool, "errors": [...], "synced_at": iso, ... }
          }

        Best-effort:
        - never raises
        - soft derived DBs do not emit *__error keys
        - IDs that are actually pages (common for SOP_* vars) auto-fallback to retrieve_page
        """
        synced_at = datetime.utcnow().isoformat() + "Z"
        errors: List[str] = []

        payload: Dict[str, Any] = {
            "last_sync": synced_at,
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

        async def _fetch_db(db_key: str, db_id: str) -> List[Dict[str, Any]]:
            results = await self._query_db(db_id, self._snapshot_page_size)

            # Optional blocks (DB pages)
            if (
                self._snapshot_include_blocks
                and self._snapshot_blocks_page_limit > 0
                and self._snapshot_blocks_per_page_limit > 0
                and db_key in set(self._snapshot_blocks_db_keys or [])
            ):
                limited_pages = results[: int(self._snapshot_blocks_page_limit)]
                for p in limited_pages:
                    pid = p.get("id")
                    if isinstance(pid, str) and pid:
                        try:
                            p["__blocks"] = await self._retrieve_blocks_limited(
                                pid, int(self._snapshot_blocks_per_page_limit)
                            )
                        except Exception as exc:  # noqa: BLE001
                            if db_key not in self._warned_page_fallback:
                                self._warned_page_fallback.add(db_key)
                                logger.warning(
                                    "Snapshot blocks fetch failed for %s: %s",
                                    db_key,
                                    exc,
                                )

            if self._snapshot_compact:
                return [self._compact_page(p) for p in results if isinstance(p, dict)]
            return [p for p in results if isinstance(p, dict)]

        async def _fetch_page_as_list(
            db_key: str, page_id: str
        ) -> List[Dict[str, Any]]:
            page = await self._retrieve_page(page_id)

            # Optional blocks (single page)
            if (
                self._snapshot_include_blocks
                and self._snapshot_blocks_per_page_limit > 0
                and db_key in set(self._snapshot_blocks_db_keys or [])
            ):
                pid = page.get("id")
                if isinstance(pid, str) and pid:
                    try:
                        page["__blocks"] = await self._retrieve_blocks_limited(
                            pid, int(self._snapshot_blocks_per_page_limit)
                        )
                    except Exception as exc:  # noqa: BLE001
                        if db_key not in self._warned_page_fallback:
                            self._warned_page_fallback.add(db_key)
                            logger.warning(
                                "Snapshot blocks fetch failed for page %s: %s",
                                db_key,
                                exc,
                            )

            compact = self._compact_page(page) if self._snapshot_compact else page
            return [compact] if isinstance(compact, dict) else [{"raw": compact}]

        for db_key, db_id in sorted(self.db_ids.items(), key=lambda x: str(x[0])):
            k = self._normalize_db_key(db_key) or db_key
            if not isinstance(db_id, str) or not db_id.strip():
                continue

            try:
                pages = await _fetch_db(k, db_id.strip())
            except Exception as exc:  # noqa: BLE001
                err_text = str(exc)

                # 1) If ID is actually a page -> fallback to retrieve_page (no error)
                if self._looks_like_page_not_db(err_text):
                    try:
                        pages = await _fetch_page_as_list(k, db_id.strip())
                        if k not in self._warned_page_fallback:
                            self._warned_page_fallback.add(k)
                            logger.warning(
                                "Snapshot: '%s' looks like page-id; using retrieve_page fallback.",
                                k,
                            )
                    except Exception as exc2:  # noqa: BLE001
                        # If fallback fails, treat as soft skip unless hard required
                        err2 = str(exc2)
                        if (
                            self._is_soft_optional_snapshot_key(k)
                            or k in self._SOFT_DERIVED_VIEW_KEYS
                        ):
                            if k not in self._warned_inaccessible:
                                self._warned_inaccessible.add(k)
                                logger.warning(
                                    "Snapshot: '%s' page fallback failed (soft-skip): %s",
                                    k,
                                    err2,
                                )
                            continue
                        errors.append(f"{k}__error:{err2}")
                        logger.warning(
                            "Snapshot: '%s' page fallback failed (hard): %s", k, err2
                        )
                        continue

                # 2) Optional derived views: soft-skip (no error)
                elif k in self._SOFT_DERIVED_VIEW_KEYS and (
                    self._is_object_not_found(err_text)
                    or self._is_no_access(err_text)
                    or self._looks_like_page_not_db(err_text)
                ):
                    if k not in self._warned_inaccessible:
                        self._warned_inaccessible.add(k)
                        logger.warning(
                            "Snapshot: derived view '%s' not accessible (soft-skip): %s",
                            k,
                            err_text,
                        )
                    continue

                # 3) Soft optional keys: if no-access or not-found -> soft-skip (no error)
                elif self._is_soft_optional_snapshot_key(k) and (
                    self._is_object_not_found(err_text) or self._is_no_access(err_text)
                ):
                    if k not in self._warned_inaccessible:
                        self._warned_inaccessible.add(k)
                        logger.warning(
                            "Snapshot: '%s' not accessible (soft-skip): %s", k, err_text
                        )
                    continue

                # 4) Hard required -> record error
                else:
                    errors.append(f"{k}__error:{err_text}")
                    logger.warning(
                        "Snapshot: db '%s' query failed (best-effort): %s", k, err_text
                    )
                    continue

            # --- store fetched content ---
            if k == "goals":
                payload["goals"] = pages
                if not self._snapshot_compact:
                    payload["goals_summary"] = self._build_status_priority_summary(
                        pages, self.goals_status_prop, self.goals_priority_prop
                    )
                else:
                    payload["goals_summary"] = {
                        "total": len(pages),
                        "by_status": {},
                        "by_priority": {},
                    }

            elif k == "tasks":
                payload["tasks"] = pages
                if not self._snapshot_compact:
                    payload["tasks_summary"] = self._build_status_priority_summary(
                        pages, self.tasks_status_prop, self.tasks_priority_prop
                    )
                else:
                    payload["tasks_summary"] = {
                        "total": len(pages),
                        "by_status": {},
                        "by_priority": {},
                    }

            elif k == "projects":
                payload["projects"] = pages
                payload["projects_summary"] = {
                    "total": len(pages),
                    "by_status": {},
                    "by_priority": {},
                }

            elif k == "kpi":
                payload["kpi"] = pages
                payload["kpi_summary"] = {"total": len(pages)}

            elif k in ("leads", "lead"):
                payload["leads"] = pages
                payload["leads_summary"] = {"total": len(pages)}

            elif k == "agent_exchange":
                payload["agent_exchange"] = pages
                payload["agent_exchange_summary"] = {"total": len(pages)}

            elif k in ("ai_summary", "ai_weekly_summary"):
                payload["ai_summary"] = pages

            else:
                payload["extra_databases"][k] = pages

        if (
            isinstance(self._time_management_page_id, str)
            and self._time_management_page_id.strip()
        ):
            try:
                page = await self._retrieve_page(self._time_management_page_id.strip())
                payload["time_management"] = (
                    self._compact_page(page) if self._snapshot_compact else page
                )
            except Exception as exc:  # noqa: BLE001
                # time_management is soft optional
                logger.warning(
                    "Snapshot: time_management page not accessible (soft-skip): %s", exc
                )

        payload["snapshot_meta"] = {
            "ok": True,
            "errors": errors,
            "synced_at": synced_at,
            "page_size": int(self._snapshot_page_size),
            "compact": bool(self._snapshot_compact),
        }

        self.knowledge_snapshot = dict(payload)

        return {
            "payload": payload,
            "meta": {
                "ok": True,
                "success": True,
                "best_effort": True,
                "errors": errors,
                "synced_at": synced_at,
                "source": "notion_service.build_knowledge_snapshot",
            },
        }

    async def sync_knowledge_snapshot(self) -> Dict[str, Any]:
        """
        Read-only snapshot sync used by refresh_snapshot intent.

        Canon:
        - MUST NOT raise
        - MUST return stable dict result
        - MUST update KnowledgeSnapshotService (wrapper with payload+meta)
        """
        try:
            wrapper = await self.build_knowledge_snapshot()
            if not isinstance(wrapper, dict) or not isinstance(
                wrapper.get("payload"), dict
            ):
                wrapper = {
                    "payload": dict(self.knowledge_snapshot),
                    "meta": {
                        "ok": True,
                        "success": True,
                        "best_effort": True,
                        "errors": ["snapshot_wrapper_invalid"],
                        "synced_at": datetime.utcnow().isoformat() + "Z",
                        "source": "notion_service.sync_knowledge_snapshot",
                    },
                }

            try:
                KnowledgeSnapshotService.update_snapshot(wrapper)
            except Exception as exc:  # noqa: BLE001
                meta = (
                    wrapper.get("meta") if isinstance(wrapper.get("meta"), dict) else {}
                )
                errs = (
                    meta.get("errors") if isinstance(meta.get("errors"), list) else []
                )
                errs.append(f"knowledge_snapshot_service_update_failed:{exc}")
                meta["errors"] = errs
                meta["ok"] = True
                meta["success"] = True
                wrapper["meta"] = meta

            return {
                "success": True,
                "ok": True,
                "best_effort": True,
                "action": "refresh_snapshot",
                "payload": wrapper.get("payload"),
                "meta": wrapper.get("meta"),
                "errors": (wrapper.get("meta") or {}).get("errors", [])
                if isinstance(wrapper.get("meta"), dict)
                else [],
            }

        except Exception as exc:  # noqa: BLE001
            logger.exception("sync_knowledge_snapshot failed (best-effort): %s", exc)

            wrapper = {
                "payload": dict(self.knowledge_snapshot),
                "meta": {
                    "ok": True,
                    "success": True,
                    "best_effort": True,
                    "errors": [f"sync_knowledge_snapshot_failed:{exc}"],
                    "synced_at": datetime.utcnow().isoformat() + "Z",
                    "source": "notion_service.sync_knowledge_snapshot",
                },
            }
            try:
                KnowledgeSnapshotService.update_snapshot(wrapper)
            except Exception:
                pass

            return {
                "success": True,
                "ok": True,
                "best_effort": True,
                "action": "refresh_snapshot",
                "payload": wrapper.get("payload"),
                "meta": wrapper.get("meta"),
                "errors": wrapper["meta"]["errors"],
            }

    def get_knowledge_snapshot(self) -> Dict[str, Any]:
        return dict(self.knowledge_snapshot)

    async def aclose(self) -> None:
        sess = self.session
        self.session = None
        if sess is not None and not sess.closed:
            try:
                await sess.close()
            except Exception:
                pass


_NOTION_SERVICE_SINGLETON: Optional[NotionService] = None


def set_notion_service(service: NotionService) -> None:
    global _NOTION_SERVICE_SINGLETON
    _NOTION_SERVICE_SINGLETON = service


def get_notion_service() -> NotionService:
    if _NOTION_SERVICE_SINGLETON is None:
        raise RuntimeError("NotionService not initialized")
    return _NOTION_SERVICE_SINGLETON
