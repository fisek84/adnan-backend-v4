import os
import aiohttp
from typing import Dict, Any, Optional
import logging
from datetime import datetime

from models.ai_command import AICommand


class NotionService:
    """
    CANONICAL NOTION SERVICE

    - ČIST EXECUTOR
    - prima AICommand
    - mapira intent → Notion API
    - JEDINA write tačka prema Notionu
    """

    def __init__(
        self,
        api_key: str,
        goals_db_id: str,
        tasks_db_id: str,
        projects_db_id: str,
    ):
        self.api_key = api_key

        # Kanonske baze iz konstruktora (backward kompatibilno)
        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id
        self.projects_db_id = projects_db_id

        # SVE baze iz .env — centralni registry
        self.database_map: Dict[str, Optional[str]] = {
            # Core / Goals
            "goals": goals_db_id,
            "goals_active": os.getenv("NOTION_ACTIVE_GOALS_DB_ID", goals_db_id),
            "goals_blocked": os.getenv("NOTION_BLOCKED_GOALS_DB_ID"),
            "goals_completed": os.getenv("NOTION_COMPLETED_GOALS_DB_ID"),

            # Tasks / Projects
            "tasks": tasks_db_id,
            "projects": projects_db_id,
            "agent_projects": os.getenv("NOTION_AGENT_PROJECTS_DB_ID"),
            "agent_exchange": os.getenv("NOTION_AGENT_EXCHANGE_DB_ID"),

            # AI summaries / FLP / KPI / Leads
            "ai_weekly_summary": os.getenv("NOTION_AI_WEEKLY_SUMMARY_DB_ID"),
            "flp": os.getenv("NOTION_FLP_DB_ID"),
            "kpi": os.getenv("NOTION_KPI_DB_ID"),
            "leads": os.getenv("NOTION_LEAD_DB_ID"),

            # SOP-ovi (sales / partner / customer / ops)
            "outreach_sop": os.getenv("NOTION_OUTREACH_SOP_DB_ID"),
            "qualification_sop": os.getenv("NOTION_QUALIFICATION_SOP_DB_ID"),
            "follow_up_sop": os.getenv("NOTION_FOLLOW_UP_SOP_DB_ID"),
            "fsc_sop": os.getenv("NOTION_FSC_SOP_DB_ID"),
            "flp_ops_sop": os.getenv("NOTION_FLP_OPS_SOP_DB_ID"),
            "lss_sop": os.getenv("NOTION_LSS_SOP_DB_ID"),
            "partner_activation_sop": os.getenv("NOTION_PARTNER_ACTIVATION_SOP_DB_ID"),
            "partner_performance_sop": os.getenv("NOTION_PARTNER_PERFORMANCE_SOP_DB_ID"),
            "partner_leadership_sop": os.getenv("NOTION_PARTNER_LEADERSHIP_SOP_DB_ID"),
            "customer_onboarding_sop": os.getenv("NOTION_CUSTOMER_ONBOARDING_SOP_DB_ID"),
            "customer_retention_sop": os.getenv("NOTION_CUSTOMER_RETENTION_SOP_DB_ID"),
            "customer_performance_sop": os.getenv("NOTION_CUSTOMER_PERFORMANCE_SOP_DB_ID"),
            "partner_potential_sop": os.getenv("NOTION_PARTNER_POTENTIAL_SOP_DB_ID"),
            "sales_closing_sop": os.getenv("NOTION_SALES_CLOSING_SOP_DB_ID"),
        }

        self.session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(__name__)

        # Minimalni snapshot (backward kompatibilno)
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

    async def _safe_request(self, method: str, url: str, payload: Optional[Dict[str, Any]] = None):
        session = await self._get_session()
        async with session.request(method, url, json=payload) as response:
            text = await response.text()
            if response.status not in (200, 201, 202):
                raise RuntimeError(f"Notion API error {response.status}: {text}")
            return await response.json() if text else {}

    # --------------------------------------------------
    # DB RESOLUTION
    # --------------------------------------------------

    def _resolve_database_id(self, params: Dict[str, Any]) -> str:
        """
        Resolves database reference from params.

        Dozvoljeno:
        - params["database_id"]  (direktni Notion DB ID)
        - params["db_key"]       (ključ u self.database_map)
        """
        # Direktni ID ima prioritet
        db_id = params.get("database_id")
        if db_id:
            return db_id

        db_key = params.get("db_key") or params.get("database_key")
        if db_key:
            mapped = self.database_map.get(db_key)
            if not mapped:
                raise RuntimeError(f"Unknown db_key: {db_key}")
            return mapped

        # Fallback za legacy slučajeve (nije preporučeno za nove tokove)
        raise RuntimeError("Missing database reference: provide 'database_id' or 'db_key' in params")

    # --------------------------------------------------
    # EXECUTION ENTRY POINT (WRITE / GENERIC)
    # --------------------------------------------------

    async def execute(self, command: AICommand) -> Dict[str, Any]:
        """
        Jedina ulazna tačka za write/query akcije prema Notionu.

        Očekivani intent-i:
        - create_goal      (legacy + proširivo)
        - create_page      (generic page create u bilo kom DB-u)
        - update_page      (generic page update)
        - query_database   (generic DB query)
        """

        intent = command.intent
        if not intent:
            raise RuntimeError("NotionService.execute called without intent")

        params = command.params or {}

        if intent == "create_goal":
            return await self._create_goal(command, params)

        if intent == "create_page":
            return await self._create_page_generic(params)

        if intent == "update_page":
            return await self._update_page_generic(params)

        if intent == "query_database":
            return await self._query_database_generic(params)

        raise RuntimeError(f"Unsupported intent: {intent}")

    # --------------------------------------------------
    # INTENT: create_goal  (BACKWARD + PROŠIRENJE)
    # --------------------------------------------------

    async def _create_goal(self, command: AICommand, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Legacy + safe proširenje:

        - Minimalno: params["name"] (string)  → postavi Name
        - Opcionalno: params["properties"] (raw Notion properties dict)
          → merge sa generisanim Name property
        """
        name = params.get("name")
        if not name:
            raise RuntimeError("Missing goal name")

        extra_properties = params.get("properties") or {}

        base_properties: Dict[str, Any] = {
            "Name": {
                "title": [
                    {
                        "text": {
                            "content": name
                        }
                    }
                ]
            }
        }

        properties = {**base_properties, **extra_properties}

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
        }

    # --------------------------------------------------
    # INTENT: create_page (GENERIC)
    # --------------------------------------------------

    async def _create_page_generic(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generic page create u bilo kojoj bazi.

        params:
        - database_id  ili db_key
        - properties   (raw Notion properties dict)
        """
        db_id = self._resolve_database_id(params)
        properties = params.get("properties")
        if not isinstance(properties, dict) or not properties:
            raise RuntimeError("create_page requires 'properties' dict in params")

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

    # --------------------------------------------------
    # INTENT: update_page (GENERIC)
    # --------------------------------------------------

    async def _update_page_generic(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generic page update.

        params:
        - page_id     (Notion page ID)
        - properties  (partial properties dict)
        """
        page_id = params.get("page_id")
        properties = params.get("properties")

        if not page_id:
            raise RuntimeError("update_page requires 'page_id' in params")
        if not isinstance(properties, dict) or not properties:
            raise RuntimeError("update_page requires 'properties' dict in params")

        payload = {
            "properties": properties,
        }

        url = f"https://api.notion.com/v1/pages/{page_id}"

        result = await self._safe_request(
            "PATCH",
            url,
            payload,
        )

        return {
            "success": True,
            "notion_page_id": result.get("id", page_id),
        }

    # --------------------------------------------------
    # INTENT: query_database (GENERIC)
    # --------------------------------------------------

    async def _query_database_generic(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generic database query.

        params:
        - database_id  ili db_key
        - filter       (optional Notion filter object)
        - sorts        (optional Notion sorts list)
        """
        db_id = self._resolve_database_id(params)

        query_payload: Dict[str, Any] = {}
        if "filter" in params:
            query_payload["filter"] = params["filter"]
        if "sorts" in params:
            query_payload["sorts"] = params["sorts"]

        url = f"https://api.notion.com/v1/databases/{db_id}/query"

        result = await self._safe_request(
            "POST",
            url,
            query_payload if query_payload else {},
        )

        return {
            "success": True,
            "database_id": db_id,
            "results": result.get("results", []),
            "has_more": result.get("has_more", False),
            "next_cursor": result.get("next_cursor"),
        }

    # --------------------------------------------------
    # READ-ONLY SNAPSHOT
    # --------------------------------------------------

    async def sync_knowledge_snapshot(self):
        self.logger.info(">> Syncing Notion knowledge snapshot")
        self.knowledge_snapshot["last_sync"] = datetime.utcnow().isoformat()
        # (za sada ne povlačimo cijele baze; ovo je read-only hook)
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
