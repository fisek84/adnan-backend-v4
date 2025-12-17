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
    - JEDINA write/query tačka prema Notionu
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

        # SVE baze iz .env — centralni registry (apsolutna moć, ali eksplicitno)
        self.database_map: Dict[str, Optional[str]] = {
            # Core / Goals
            "goals": goals_db_id,
            "goals_active": os.getenv("NOTION_ACTIVE_GOALS_DB_ID", goals_db_id),
            "goals_blocked": os.getenv("NOTION_BLOCKED_GOALS_DB_ID"),
            "goals_completed": os.getenv("NOTION_COMPLETED_GOALS_DB_ID"),

            # Tasks / Projects / Agent
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
        db_id = params.get("database_id")
        if db_id:
            return db_id

        db_key = params.get("db_key") or params.get("database_key")
        if db_key:
            mapped = self.database_map.get(db_key)
            if not mapped:
                raise RuntimeError(f"Unknown db_key: {db_key}")
            return mapped

        raise RuntimeError("Missing database reference: provide 'database_id' or 'db_key' in params")

    # --------------------------------------------------
    # PROPERTY DSL → NOTION PROPERTIES
    # --------------------------------------------------

    def _build_properties_from_spec(self, property_specs: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        """
        High-level DSL → Notion properties.

        property_specs primjer:

        {
          "Name": { "type": "title", "text": "EVO-TASK-RAW-001" },
          "Status": { "type": "select", "name": "To Do" },
          "Due Date": { "type": "date", "start": "2025-12-20" },
          "Goal": { "type": "relation", "page_ids": ["<goal_page_id>"] }
        }
        """
        properties: Dict[str, Any] = {}

        for prop_name, spec in property_specs.items():
            if not isinstance(spec, dict):
                raise RuntimeError(f"Invalid property spec for '{prop_name}'")

            p_type = spec.get("type")
            if not p_type:
                raise RuntimeError(f"Property '{prop_name}' missing type")

            # TITLE
            if p_type == "title":
                text = spec.get("text") or spec.get("content")
                if not isinstance(text, str):
                    raise RuntimeError(f"title property '{prop_name}' requires 'text' string")
                properties[prop_name] = {
                    "title": [
                        {
                            "text": {
                                "content": text
                            }
                        }
                    ]
                }

            # RICH TEXT
            elif p_type == "rich_text":
                text = spec.get("text") or spec.get("content")
                if not isinstance(text, str):
                    raise RuntimeError(f"rich_text property '{prop_name}' requires 'text' string")
                properties[prop_name] = {
                    "rich_text": [
                        {
                            "text": {
                                "content": text
                            }
                        }
                    ]
                }

            # NUMBER
            elif p_type == "number":
                value = spec.get("value")
                if not isinstance(value, (int, float)):
                    raise RuntimeError(f"number property '{prop_name}' requires numeric 'value'")
                properties[prop_name] = {
                    "number": value
                }

            # SELECT
            elif p_type == "select":
                name = spec.get("name") or spec.get("value")
                if not isinstance(name, str):
                    raise RuntimeError(f"select property '{prop_name}' requires 'name' string")
                properties[prop_name] = {
                    "select": {
                        "name": name
                    }
                }

            # MULTI_SELECT
            elif p_type == "multi_select":
                values = spec.get("values") or spec.get("names")
                if not isinstance(values, list):
                    raise RuntimeError(f"multi_select property '{prop_name}' requires list 'values'")
                properties[prop_name] = {
                    "multi_select": [
                        {"name": v} for v in values
                    ]
                }

            # DATE
            elif p_type == "date":
                start = spec.get("start")
                end = spec.get("end")
                if not isinstance(start, str):
                    raise RuntimeError(f"date property '{prop_name}' requires 'start' ISO date string")
                properties[prop_name] = {
                    "date": {
                        "start": start,
                        "end": end,
                    }
                }

            # RELATION
            elif p_type == "relation":
                page_ids = spec.get("page_ids") or spec.get("ids")
                if not isinstance(page_ids, list) or not page_ids:
                    raise RuntimeError(f"relation property '{prop_name}' requires non-empty list 'page_ids'")
                properties[prop_name] = {
                    "relation": [
                        {"id": pid} for pid in page_ids
                    ]
                }

            # CHECKBOX
            elif p_type == "checkbox":
                value = bool(spec.get("value", False))
                properties[prop_name] = {
                    "checkbox": value
                }

            # URL
            elif p_type == "url":
                url = spec.get("url")
                if not isinstance(url, str):
                    raise RuntimeError(f"url property '{prop_name}' requires 'url' string")
                properties[prop_name] = {
                    "url": url
                }

            else:
                raise RuntimeError(f"Unsupported property type '{p_type}' for '{prop_name}'")

        return properties

    # --------------------------------------------------
    # EXECUTION ENTRY POINT (WRITE / QUERY)
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
        - Opcionalno: params["property_specs"] (high-level DSL) → merge
        """
        name = params.get("name")
        if not name:
            raise RuntimeError("Missing goal name")

        raw_properties: Dict[str, Any] = params.get("properties") or {}
        property_specs: Dict[str, Any] = params.get("property_specs") or {}

        # Bazni Name property
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

        # DSL → properties
        dsl_properties: Dict[str, Any] = {}
        if property_specs:
            if not isinstance(property_specs, dict):
                raise RuntimeError("property_specs must be a dict")
            dsl_properties = self._build_properties_from_spec(property_specs)

        # Merge redoslijed (prioritet):
        # 1) base Name
        # 2) DSL properties
        # 3) raw properties (ako korisnik želi full override)
        properties = {**base_properties, **dsl_properties, **raw_properties}

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
        - property_specs (opcionalno DSL; koristi se ako properties nije postavljen)
        """
        db_id = self._resolve_database_id(params)

        raw_properties: Dict[str, Any] = params.get("properties") or {}
        property_specs: Dict[str, Any] = params.get("property_specs") or {}

        if raw_properties:
            if not isinstance(raw_properties, dict):
                raise RuntimeError("'properties' must be a dict when provided")
            properties = raw_properties
        else:
            if not isinstance(property_specs, dict) or not property_specs:
                raise RuntimeError("create_page requires 'properties' or 'property_specs' in params")
            properties = self._build_properties_from_spec(property_specs)

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
        - page_id        (Notion page ID)
        - properties     (partial properties dict)
        - property_specs (opcionalno DSL; koristi se ako properties nije postavljen)
        """
        page_id = params.get("page_id")
        raw_properties: Dict[str, Any] = params.get("properties") or {}
        property_specs: Dict[str, Any] = params.get("property_specs") or {}

        if not page_id:
            raise RuntimeError("update_page requires 'page_id' in params")

        if raw_properties:
            if not isinstance(raw_properties, dict):
                raise RuntimeError("'properties' must be a dict when provided")
            properties = raw_properties
        else:
            if not isinstance(property_specs, dict) or not property_specs:
                raise RuntimeError("update_page requires 'properties' or 'property_specs' in params")
            properties = self._build_properties_from_spec(property_specs)

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
