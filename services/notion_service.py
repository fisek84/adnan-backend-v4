import aiohttp
import asyncio
from typing import Dict, Any, Optional
import logging
from datetime import datetime


class NotionService:
    """
    Finalna stabilna verzija Notion servisa.

    POSTOJEĆE (NE DIRATI):
    - async metode za execution
    - sync wrapperi
    - smart_process / SOP execution

    DODANO (FAZA 1):
    - READ-ONLY knowledge ingestion
    - snapshot poslovne istine
    - bez ikakvog execution-a
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

        # --------------------------------------------------------------
        # READ-ONLY KNOWLEDGE SNAPSHOT (CO-CEO SVJESNOST)
        # --------------------------------------------------------------
        self.knowledge_snapshot: Dict[str, Any] = {
            "last_sync": None,
            "goals": [],
            "tasks": [],
            "projects": [],
        }

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
    # BASIC ASYNC WRAPPERS (EXECUTION — NE DIRATI)
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
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                return asyncio.ensure_future(coro)
            return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    # ---------------------------------------------------------------------
    # SMART PROCESS (EXECUTION — NE DIRATI)
    # ---------------------------------------------------------------------
    async def smart_process(self, user_input: str, target_db: str):
        if not target_db:
            return {"ok": False, "error": "Playbook nije odredio DB."}

        text = user_input.lower()

        if any(w in text for w in ["kreiraj", "napravi", "dodaj", "create"]):
            title = user_input.strip()
            payload = {
                "parent": {"database_id": target_db},
                "properties": {"Name": {"title": [{"text": {"content": title}}]}},
            }
            return await self.create_page(payload)

        if any(w in text for w in ["prikaži", "pokaži", "query", "lista", "list"]):
            return await self.query_database(target_db)

        return {"ok": True, "note": "SmartProcess: nije prepoznata operacija.", "db": target_db}

    def smart_process_sync(self, user_input: str, target_db: str):
        return self._sync(self.smart_process(user_input, target_db))

    # ---------------------------------------------------------------------
    # GENERAL PROCESS (EXECUTION — NE DIRATI)
    # ---------------------------------------------------------------------
    async def process(self, user_input: str):
        from services.decision_engine.playbook_engine import get_db_id

        db = get_db_id(user_input)
        if not db:
            return {"ok": False, "error": "Ne mogu pronaći odgovarajuću Notion bazu."}

        return await self.smart_process(user_input, db)

    def process_sync(self, user_input: str):
        return self._sync(self.process(user_input))

    # ---------------------------------------------------------------------
    # SOP PROCESS (EXECUTION — NE DIRATI)
    # ---------------------------------------------------------------------
    async def handle_sop(self, user_input: str):
        from services.decision_engine.playbook_engine import get_db_id

        sop_db = get_db_id("sop")
        if not sop_db:
            return {"ok": False, "error": "SOP DB nije pronađena."}

        return await self.smart_process(user_input, sop_db)

    def handle_sop_sync(self, user_input: str):
        return self._sync(self.handle_sop(user_input))

    # =====================================================================
    # ================== FAZA 1 — READ ONLY COO / CEO ======================
    # =====================================================================

    async def _read_db_snapshot(self, db_id: str):
        """
        Interna READ-ONLY metoda.
        Nikad ne piše.
        Nikad ne mijenja.
        """
        res = await self.query_database(db_id)
        if not res.get("ok"):
            return []

        items = []
        for r in res["data"].get("results", []):
            props = r.get("properties", {})
            name = ""
            if "Name" in props and props["Name"]["title"]:
                name = props["Name"]["title"][0]["text"]["content"]

            items.append({
                "id": r.get("id"),
                "name": name,
                "raw": props,
            })

        return items

    async def sync_knowledge_snapshot(self):
        """
        Periodično čitanje Notiona.
        Ovo je 'poslovna svijest' Adnan.AI-ja.
        """
        self.logger.info(">> Syncing Notion knowledge snapshot")

        self.knowledge_snapshot["goals"] = await self._read_db_snapshot(self.goals_db_id)
        self.knowledge_snapshot["tasks"] = await self._read_db_snapshot(self.tasks_db_id)
        self.knowledge_snapshot["projects"] = await self._read_db_snapshot(self.projects_db_id)
        self.knowledge_snapshot["last_sync"] = datetime.utcnow().isoformat()

        return {
            "ok": True,
            "summary": "Knowledge snapshot updated",
            "counts": {
                "goals": len(self.knowledge_snapshot["goals"]),
                "tasks": len(self.knowledge_snapshot["tasks"]),
                "projects": len(self.knowledge_snapshot["projects"]),
            },
        }

    def sync_knowledge_snapshot_sync(self):
        return self._sync(self.sync_knowledge_snapshot())

    def get_knowledge_snapshot(self) -> Dict[str, Any]:
        """
        READ-ONLY getter.
        Ovdje CEO 'zna firmu'.
        """
        return self.knowledge_snapshot
