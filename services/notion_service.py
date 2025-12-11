import aiohttp
import asyncio
from typing import Dict, Any, Optional
import logging


class NotionService:
    """
    Finalna stabilna verzija Notion servisa.
    - async metode (koristi ih Orchestrator SYNC wrapper)
    - sync wrapper funkcije: process_sync(), smart_process_sync(), handle_sop_sync()
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

        self.session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(__name__)

    # ---------------------------------------------------------------------
    # INTERNAL SESSION HANDLING
    # ---------------------------------------------------------------------
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

    # ---------------------------------------------------------------------
    # BASIC ASYNC WRAPPERS
    # ---------------------------------------------------------------------
    async def create_page(self, payload: Dict[str, Any]):
        return await self._safe_request("POST", "https://api.notion.com/v1/pages", payload)

    async def update_page(self, page_id: str, payload: Dict[str, Any]):
        return await self._safe_request("PATCH", f"https://api.notion.com/v1/pages/{page_id}", payload)

    async def query_database(self, db_id: str, payload=None):
        return await self._safe_request(
            "POST",
            f"https://api.notion.com/v1/databases/{db_id}/query",
            payload or {},
        )

    async def delete_page(self, page_id: str):
        return await self._safe_request(
            "PATCH",
            f"https://api.notion.com/v1/pages/{page_id}",
            {"archived": True},
        )

    # ---------------------------------------------------------------------
    # SYNC ADAPTER (FASTAPI-SAFE)
    # ---------------------------------------------------------------------
    def _sync(self, coro):
        """
        Sigurni sync adapter koji NE koristi asyncio.run()
        i time NE ruši FastAPI event loop.
        """
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return asyncio.ensure_future(coro)
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    # ---------------------------------------------------------------------
    # SMART PROCESS (ASYNC)
    # ---------------------------------------------------------------------
    async def smart_process(self, user_input: str, target_db: str):
        if not target_db:
            return {"ok": False, "error": "Playbook nije odredio DB."}

        text = user_input.lower()

        # CREATE
        if any(w in text for w in ["kreiraj", "napravi", "dodaj", "create"]):
            title = user_input.strip()
            payload = {
                "parent": {"database_id": target_db},
                "properties": {"Name": {"title": [{"text": {"content": title}}]}}
            }
            return await self.create_page(payload)

        # QUERY
        if any(w in text for w in ["prikaži", "pokaži", "query", "lista", "list"]):
            return await self.query_database(target_db)

        return {"ok": True, "note": "SmartProcess: nije prepoznata operacija.", "db": target_db}

    # ---------------------------------------------------------------------
    # SYNC SMART PROCESS
    # ---------------------------------------------------------------------
    def smart_process_sync(self, user_input: str, target_db: str):
        return self._sync(self.smart_process(user_input, target_db))

    # ---------------------------------------------------------------------
    # GENERAL PROCESS (ASYNC)
    # ---------------------------------------------------------------------
    async def process(self, user_input: str):
        """
        General fuzzy matching prema bazi kroz Playbook Engine.
        """
        from services.decision_engine.playbook_engine import get_db_id

        db = get_db_id(user_input)
        if not db:
            return {"ok": False, "error": "Ne mogu pronaći odgovarajuću Notion bazu."}

        return await self.smart_process(user_input, db)

    # SYNC WRAPPER
    def process_sync(self, user_input: str):
        return self._sync(self.process(user_input))

    # ---------------------------------------------------------------------
    # SOP PROCESS
    # ---------------------------------------------------------------------
    async def handle_sop(self, user_input: str):
        from services.decision_engine.playbook_engine import get_db_id

        sop_db = get_db_id("sop")
        if not sop_db:
            return {"ok": False, "error": "SOP DB nije pronađena."}

        return await self.smart_process(user_input, sop_db)

    # SYNC WRAPPER
    def handle_sop_sync(self, user_input: str):
        return self._sync(self.handle_sop(user_input))
