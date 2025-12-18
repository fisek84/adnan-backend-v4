import os
import aiohttp
from typing import Dict, Any, Optional
import logging
from datetime import datetime
import re

from services.knowledge_snapshot_service import KnowledgeSnapshotService


class NotionService:
    """
    CANONICAL NOTION SERVICE

    - ČIST EXECUTOR
    - prima AICommand
    - mapira intent → Notion API
    - JEDINA write/read tačka prema Notionu za AI agente
    """

    def __init__(
        self,
        api_key: str,
        goals_db_id: str,
        tasks_db_id: str,
        projects_db_id: str,
    ):
        self.api_key = api_key
        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id
        self.projects_db_id = projects_db_id

        # Centralna mapa svih baza kojima AI smije pristupiti
        self.db_ids: Dict[str, str] = {
            "goals": goals_db_id,
            "tasks": tasks_db_id,
            "projects": projects_db_id,
        }

        # Dodatne baze iz .env (ako postoje)
        extra_env_map = {
            "active_goals": "NOTION_ACTIVE_GOALS_DB_ID",
            "blocked_goals": "NOTION_BLOCKED_GOALS_DB_ID",
            "completed_goals": "NOTION_COMPLETED_GOALS_DB_ID",
            "agent_exchange": "NOTION_AGENT_EXCHANGE_DB_ID",
            "agent_projects": "NOTION_AGENT_PROJECTS_DB_ID",
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
        }

        for key, env_name in extra_env_map.items():
            value = os.getenv(env_name)
            if value:
                self.db_ids[key] = value

        # Config za agregaciju (respektuje stvarna imena property-ja u DB)
        self.goals_status_prop = os.getenv("NOTION_GOALS_STATUS_PROP_NAME", "Status")
        self.goals_priority_prop = os.getenv("NOTION_GOALS_PRIORITY_PROP_NAME", "Priority")
        self.tasks_status_prop = os.getenv("NOTION_TASKS_STATUS_PROP_NAME", "Status")
        self.tasks_priority_prop = os.getenv("NOTION_TASKS_PRIORITY_PROP_NAME", "Priority")

        self.session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(__name__)

        # In-memory knowledge snapshot (READ-ONLY za ostatak sistema)
        self.knowledge_snapshot: Dict[str, Any] = {
            "last_sync": None,
            "goals": [],
            "tasks": [],
            "projects": [],
            "goals_summary": None,
            "tasks_summary": None,
        }

    # --------------------------------------------------
    # SESSION
    # --------------------------------------------------
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Notion-Version": "2022-06-28",
                }
            )
        return self.session

    async def _safe_request(self, method: str, url: str, payload=None):
        session = await self._get_session()
        async with session.request(method, url, json=payload) as response:
            text = await response.text()
            if response.status not in (200, 201, 202):
                raise RuntimeError(f"Notion API error {response.status}: {text}")
            return await response.json() if text else {}

    # --------------------------------------------------
    # HELPERS
    # --------------------------------------------------
    def _resolve_db_id(
        self,
        db_key: Optional[str],
        database_id: Optional[str],
    ) -> str:
        if database_id:
            return database_id
        if not db_key:
            raise RuntimeError("Database not specified (db_key or database_id required).")
        if db_key not in self.db_ids:
            raise RuntimeError(f"Unknown db_key '{db_key}' for NotionService.")
        return self.db_ids[db_key]

    def _build_properties_from_specs(
        self,
        specs: Optional[Dict[str, Any]],
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
                props[prop_name] = {
                    "title": [
                        {
                            "text": {"content": text}
                        }
                    ]
                }

            elif spec_type == "rich_text":
                text = spec.get("text") or ""
                props[prop_name] = {
                    "rich_text": [
                        {
                            "text": {"content": text}
                        }
                    ]
                }

            elif spec_type == "select":
                name = spec.get("name")
                if name:
                    props[prop_name] = {
                        "select": {"name": name}
                    }

            elif spec_type == "multi_select":
                names = spec.get("names") or []
                props[prop_name] = {
                    "multi_select": [
                        {"name": n} for n in names if n
                    ]
                }

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
                value = bool(spec.get("value"))
                props[prop_name] = {"checkbox": value}

            elif spec_type == "number":
                value = spec.get("value")
                if value is not None:
                    props[prop_name] = {"number": value}

            # Nepoznat tip – ignorišemo (bez rušenja)

        return props

    def _extract_select_name(self, prop: Optional[Dict[str, Any]]) -> Optional[str]:
        """
        Ekstrahuje ime iz Notion select/status property-ja.
        Radi i za:
        - { "status": { "name": ... } }
        - { "select": { "name": ... } }
        """
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
        """
        Minimalni agregat: brojanje po Status + Priority.
        Property imena dolaze iz .env, ali fallback je na 'Status' i 'Priority'.
        """
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

    # --------------------------------------------------
    # GOAL TEXT PARSER (kreiraj cilj ...)
    # --------------------------------------------------
    def _parse_goal_command_text(self, text: str):
        """
        Pokušava iz CEO komande izvući:
        - goal_name
        - status (Status property)
        - priority (Priority property)
        - description (ostatak / podciljevi)

        Ako parsing ne uspije, vraća samo originalni tekst kao goal_name.
        """
        if not text:
            return None, None, None, None

        raw = text.strip()
        lower = raw.lower()

        # Normalizuj 'cilj' u 'goal' da regex bude jednostavniji
        lower_norm = lower.replace("cilj", "goal")

        # Nađi poziciju prvog ključnog pojma (status/prioritet/priority)
        first_kw_idx = len(raw)
        for kw in ("status", "prioritet", "priority"):
            idx = lower_norm.find(kw)
            if idx != -1 and idx < first_kw_idx:
                first_kw_idx = idx

        name_segment = raw
        if first_kw_idx != len(raw):
            name_segment = raw[:first_kw_idx].strip(" ,.-")

        # Ukloni glagole tipa "kreiraj cilj", "create goal" itd.
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

        # Status
        status = None
        m_status = re.search(r"(?i)status[: ]+([A-Za-zčćžšđ\s]+)", raw)
        if m_status:
            status = m_status.group(1).strip(" ,.-")

        # Priority / Prioritet
        priority = None
        m_prio = re.search(r"(?i)(prioritet|priority)[: ]+([A-Za-zčćžšđ\s]+)", raw)
        if m_prio:
            priority = m_prio.group(2).strip(" ,.-")

        # Podcilj → opis
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
        Jedina ulazna tačka za AI write/read akcije ka Notionu.
        """
        if not getattr(command, "intent", None):
            raise RuntimeError("NotionService called without intent")

        intent = command.intent
        params = command.params or {}

        # ----------------------------------------------
        # LEGACY / GOAL CREATE (goals DB)
        # ----------------------------------------------
        if intent == "create_goal":
            raw_name = params.get("name")
            if not raw_name:
                raise RuntimeError("Missing goal name")

            goal_name, status, priority, description = self._parse_goal_command_text(raw_name)

            properties: Dict[str, Any] = {
                "Name": {
                    "title": [
                        {
                            "text": {
                                "content": goal_name or raw_name
                            }
                        }
                    ]
                }
            }

            if status:
                properties[self.goals_status_prop] = {
                    "status": {"name": status}
                }

            if priority:
                properties[self.goals_priority_prop] = {
                    "select": {"name": priority}
                }

            if description:
                properties["Description"] = {
                    "rich_text": [
                        {
                            "text": {
                                "content": description
                            }
                        }
                    ]
                }

            payload = {
                "parent": {"database_id": self.goals_db_id},
                "properties": properties,
            }

            result = await self._safe_request(
                "POST",
                "https://api.notion.com/v1/pages",
                payload,
            )

            return {
                "success": True,
                "notion_page_id": result.get("id"),
                "database_id": self.goals_db_id,
            }

        # ----------------------------------------------
        # GENERIC CREATE_PAGE (bilo koja DB)
        # ----------------------------------------------
        if intent == "create_page":
            db_key = params.get("db_key")
            database_id = params.get("database_id")
            property_specs = params.get("property_specs") or {}
            properties = params.get("properties")

            db_id = self._resolve_db_id(db_key, database_id)

            if property_specs and not properties:
                properties = self._build_properties_from_specs(property_specs)

            if not properties:
                raise RuntimeError("create_page requires properties or property_specs")

            payload = {
                "parent": {"database_id": db_id},
                "properties": properties,
            }

            result = await self._safe_request(
                "POST",
                "https://api.notion.com/v1/pages",
                payload,
            )

            return {
                "success": True,
                "notion_page_id": result.get("id"),
                "database_id": db_id,
            }

        # ----------------------------------------------
        # GENERIC UPDATE_PAGE (bilo koja page)
        # ----------------------------------------------
        if intent == "update_page":
            page_id = params.get("page_id")
            if not page_id:
                raise RuntimeError("update_page requires page_id")

            property_specs = params.get("property_specs") or {}
            properties = params.get("properties")

            if property_specs and not properties:
                properties = self._build_properties_from_specs(property_specs)

            if not properties:
                raise RuntimeError("update_page requires properties or property_specs")

            payload = {
                "properties": properties,
            }

            result = await self._safe_request(
                "PATCH",
                f"https://api.notion.com/v1/pages/{page_id}",
                payload,
            )

            return {
                "success": True,
                "notion_page_id": result.get("id", page_id),
            }

        # ----------------------------------------------
        # GENERIC QUERY_DATABASE (READ-ONLY)
        # ----------------------------------------------
        if intent == "query_database":
            db_key = params.get("db_key")
            database_id = params.get("database_id")
            db_id = self._resolve_db_id(db_key, database_id)

            filters = params.get("filters")
            sorts = params.get("sorts")
            page_size = params.get("page_size", 50)

            payload: Dict[str, Any] = {"page_size": page_size}

            if filters:
                # podržavamo ili dict (direct Notion filter) ili list[dict] → AND
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

        raise RuntimeError(f"Unsupported intent: {command.intent}")

    # --------------------------------------------------
    # READ-ONLY SNAPSHOT (goals/tasks → agregati)
    # --------------------------------------------------
    async def sync_knowledge_snapshot(self):
        """
        READ-ONLY sync Notion stanja u in-memory snapshot:
        - goals (lista)
        - tasks (lista)
        - goals_summary (by_status/by_priority)
        - tasks_summary (by_status/by_priority)

        NEMA write-a u Notion, NEMA promjene identiteta.
        """
        self.logger.info(">> Syncing Notion knowledge snapshot")

        snapshot: Dict[str, Any] = {
            "last_sync": datetime.utcnow().isoformat(),
            "goals": [],
            "tasks": [],
            "projects": [],
            "goals_summary": None,
            "tasks_summary": None,
        }

        goals_results = []
        tasks_results = []

        # --- GOALS ---
        if self.goals_db_id:
            try:
                goals_resp = await self._safe_request(
                    "POST",
                    f"https://api.notion.com/v1/databases/{self.goals_db_id}/query",
                    {"page_size": 100},
                )
                goals_results = goals_resp.get("results", []) or []
                snapshot["goals"] = goals_results
                snapshot["goals_summary"] = self._build_status_priority_summary(
                    goals_results,
                    status_prop_name=self.goals_status_prop,
                    priority_prop_name=self.goals_priority_prop,
                )
            except Exception as exc:
                self.logger.exception("Failed to sync goals snapshot from Notion")
                snapshot["goals_error"] = str(exc)

        # --- TASKS ---
        if self.tasks_db_id:
            try:
                tasks_resp = await self._safe_request(
                    "POST",
                    f"https://api.notion.com/v1/databases/{self.tasks_db_id}/query",
                    {"page_size": 100},
                )
                tasks_results = tasks_resp.get("results", []) or []
                snapshot["tasks"] = tasks_results
                snapshot["tasks_summary"] = self._build_status_priority_summary(
                    tasks_results,
                    status_prop_name=self.tasks_status_prop,
                    priority_prop_name=self.tasks_priority_prop,
                )
            except Exception as exc:
                self.logger.exception("Failed to sync tasks snapshot from Notion")
                snapshot["tasks_error"] = str(exc)

        # zapamti lokalno
        self.knowledge_snapshot = snapshot

        # objavi u globalni KnowledgeSnapshotService (READ-ONLY)
        KnowledgeSnapshotService.update_snapshot(snapshot)

        self.logger.info(
            ">> Notion knowledge snapshot synced "
            f"(goals={len(goals_results)}, tasks={len(tasks_results)})"
        )

        return {
            "ok": True,
            "last_sync": snapshot["last_sync"],
            "total_goals": len(goals_results),
            "total_tasks": len(tasks_results),
        }

    def get_knowledge_snapshot(self) -> Dict[str, Any]:
        return dict(self.knowledge_snapshot)


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
