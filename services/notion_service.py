import aiohttp
import asyncio
from typing import Dict, Any, Optional
import logging

_global_notion_service = None


def set_notion_service(instance):
    global _global_notion_service
    _global_notion_service = instance


def get_notion_service():
    if _global_notion_service is None:
        raise RuntimeError("NotionService has not been initialized yet.")
    return _global_notion_service


class NotionService:
    def __init__(
        self,
        api_key: str,
        goals_db_id: str,
        tasks_db_id: str,
        projects_db_id: str,
        active_goals_db_id: str = None,
        agent_exchange_db_id: str = None,
        agent_projects_db_id: str = None,
        ai_weekly_summary_db_id: str = None,
        blocked_goals_db_id: str = None,
        completed_goals_db_id: str = None,
        lead_db_id: str = None,
        kpi_db_id: str = None,
        flp_db_id: str = None
    ):
        self.api_key = api_key
        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id
        self.projects_db_id = projects_db_id

        # Extra DBs
        self.active_goals_db_id = active_goals_db_id
        self.agent_exchange_db_id = agent_exchange_db_id
        self.agent_projects_db_id = agent_projects_db_id
        self.ai_weekly_summary_db_id = ai_weekly_summary_db_id
        self.blocked_goals_db_id = blocked_goals_db_id
        self.completed_goals_db_id = completed_goals_db_id
        self.lead_db_id = lead_db_id
        self.kpi_db_id = kpi_db_id
        self.flp_db_id = flp_db_id

        self.session: Optional[aiohttp.ClientSession] = None

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

    # ------------------------------------------------------------
    # SESSION HANDLER
    # ------------------------------------------------------------
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

    # ------------------------------------------------------------
    # SAFE REQUEST EXECUTOR
    # ------------------------------------------------------------
    async def _safe_request(self, method: str, url: str, payload: Dict[str, Any] = None):
        session = await self._get_session()
        try:
            async with session.request(method, url, json=payload) as response:
                status = response.status
                text = await response.text()

                if status not in (200, 201, 202):
                    return {"ok": False, "status": status, "error": text}

                data = await response.json() if text else {}
                return {"ok": True, "status": status, "data": data}

        except Exception as e:
            return {"ok": False, "status": 500, "error": str(e)}

    # ------------------------------------------------------------
    # ASYNC CORE FUNCTIONS
    # ------------------------------------------------------------
    async def create_page(self, payload):
        return await self._safe_request("POST", "https://api.notion.com/v1/pages", payload)

    async def update_page(self, page_id, payload):
        return await self._safe_request("PATCH", f"https://api.notion.com/v1/pages/{page_id}", payload)

    async def delete_page(self, page_id):
        payload = {"archived": True}
        return await self._safe_request("PATCH", f"https://api.notion.com/v1/pages/{page_id}", payload)

    async def query_database(self, db_id: str, filter_payload=None):
        return await self._safe_request(
            "POST",
            f"https://api.notion.com/v1/databases/{db_id}/query",
            filter_payload or {},
        )

    # =====================================================================
    # SMART PROCESS — ASYNC
    # =====================================================================
    async def smart_process(self, user_input: str, target_db: Optional[str]):
        if not target_db:
            return {"ok": False, "error": "Playbook nije mogao odrediti Notion database."}

        text = user_input.lower()

        # CREATE
        if any(w in text for w in ["dodaj", "napravi", "kreiraj", "create", "add"]):
            title = user_input.strip()
            payload = {
                "parent": {"database_id": target_db},
                "properties": {"Name": {"title": [{"text": {"content": title}}]}},
            }
            return await self.create_page(payload)

        # QUERY
        if any(w in text for w in ["prikaži", "pokaži", "list", "query", "svi", "pregled"]):
            return await self.query_database(target_db)

        return {"ok": True, "note": "No specific action detected", "db": target_db}

    # =====================================================================
    # SOP + GENERAL PROCESS — ASYNC
    # =====================================================================
    async def handle_sop(self, user_input: str):
        from services.decision_engine.playbook_engine import get_db_id
        sop_db = get_db_id("sop")
        if not sop_db:
            return {"ok": False, "error": "Nema SOP baze."}

        return await self.smart_process(user_input, sop_db)

    async def process(self, user_input: str):
        from services.decision_engine.playbook_engine import get_db_id
        db = get_db_id(user_input)
        if not db:
            return {"ok": False, "error": "Ne mogu pronaći Notion bazu."}

        return await self.smart_process(user_input, db)

    # =====================================================================
    # SYNC WRAPPERS — FIX FOR ORCHESTRATOR (NO MORE coroutine ERRORS)
    # =====================================================================

    def _sync(self, coro):
        try:
            return asyncio.get_event_loop().run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    def sync_create_page(self, payload):
        return self._sync(self.create_page(payload))

    def sync_update_page(self, page_id, payload):
        return self._sync(self.update_page(page_id, payload))

    def sync_delete_page(self, page_id):
        return self._sync(self.delete_page(page_id))

    def sync_query_database(self, db_id, filter_payload=None):
        return self._sync(self.query_database(db_id, filter_payload))

    def sync_smart_process(self, user_input, target_db):
        return self._sync(self.smart_process(user_input, target_db))

    def sync_process(self, user_input):
        return self._sync(self.process(user_input))

    def sync_handle_sop(self, user_input):
        return self._sync(self.handle_sop(user_input))
