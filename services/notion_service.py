import aiohttp
import asyncio
from typing import Dict, Any, Optional


class NotionService:
    def __init__(self, api_key: str, goals_db_id: str, tasks_db_id: str):
        self.api_key = api_key
        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id
        self.session: Optional[aiohttp.ClientSession] = None

    # ============================================================
    # LAZY SESSION (REQUIRED FOR RENDER)
    # ============================================================
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Notion-Version": "2022-06-28"
                }
            )
        return self.session

    # ============================================================
    # GENERIC REQUEST (FIXED)
    # ============================================================
    async def _request(self, method: str, url: str, payload: Dict[str, Any] = None):
        session = await self._get_session()

        async with session.request(method, url, json=payload) as response:

            # --- FIX: Accept Notion status 200 or 201 (real create response)
            if response.status not in (200, 201):
                text = await response.text()
                return {
                    "ok": False,
                    "status": response.status,
                    "error": text
                }

            data = await response.json()
            return {"ok": True, "data": data}

    # ============================================================
    # QUERY DATABASE
    # ============================================================
    async def query_database(self, db_id: str):
        url = f"https://api.notion.com/v1/databases/{db_id}/query"
        return await self._request("POST", url)

    # ============================================================
    # CREATE PAGE
    # ============================================================
    async def create_page(self, payload: Dict[str, Any]):
        url = "https://api.notion.com/v1/pages"
        return await self._request("POST", url, payload)

    # ============================================================
    # UPDATE PAGE
    # ============================================================
    async def update_page(self, page_id: str, payload: Dict[str, Any]):
        url = f"https://api.notion.com/v1/pages/{page_id}"
        return await self._request("PATCH", url, payload)

    # ============================================================
    # CLOSE SESSION
    # ============================================================
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()