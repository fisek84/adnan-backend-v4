import os
import aiohttp
from typing import Dict, Any, Optional
import logging
from datetime import datetime


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

        self.session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(__name__)

        self.knowledge_snapshot: Dict[str, Any] = {
            "last_sync": None,
            "goals": [],
            "tasks": [],
            "projects": [],
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
            name = params.get("name")
            if not name:
                raise RuntimeError("Missing goal name")

            payload = {
                "parent": {"database_id": self.goals_db_id},
                "properties": {
                    "Name": {
                        "title": [
                            {
                                "text": {
                                    "content": name
                                }
                            }
                        ]
                    }
                },
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
    # READ-ONLY SNAPSHOT (još uvijek stub)
    # --------------------------------------------------
    async def sync_knowledge_snapshot(self):
        self.logger.info(">> Syncing Notion knowledge snapshot")
        self.knowledge_snapshot["last_sync"] = datetime.utcnow().isoformat()
        return {"ok": True}

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
