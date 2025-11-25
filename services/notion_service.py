import aiohttp
from typing import Dict, Any, Optional


class NotionService:
    def __init__(self, api_key: str, goals_db_id: str, tasks_db_id: str):
        self.api_key = api_key
        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id
        self.session: Optional[aiohttp.ClientSession] = None

    # ============================================================
    # SAFE SESSION (Render compatible)
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
    # SAFE REQUEST LAYER (NE RUŠI SERVER)
    # ============================================================
    async def _safe_request(self, method: str, url: str, payload: Dict[str, Any] = None):
        session = await self._get_session()

        try:
            async with session.request(method, url, json=payload) as response:

                # Accept 200 & 201
                if response.status not in (200, 201):
                    text = await response.text()
                    return {
                        "ok": False,
                        "status": response.status,
                        "error": text
                    }

                data = await response.json()
                return {
                    "ok": True,
                    "status": response.status,
                    "data": data
                }

        except Exception as e:
            return {
                "ok": False,
                "status": 500,
                "error": str(e)
            }

    # ============================================================
    # PUBLIC API METHODS
    # ============================================================
    async def create_page(self, payload: Dict[str, Any]):
        url = "https://api.notion.com/v1/pages"
        return await self._safe_request("POST", url, payload)

    async def update_page(self, page_id: str, payload: Dict[str, Any]):
        url = f"https://api.notion.com/v1/pages/{page_id}"
        return await self._safe_request("PATCH", url, payload)

    async def query_database(self, db_id: str):
        url = f"https://api.notion.com/v1/databases/{db_id}/query"
        return await self._safe_request("POST", url, {})

    # ============================================================
    # DELETE (ARCHIVE) PAGE IN NOTION
    # ============================================================
    async def delete_page(self, page_id: str):
        url = f"https://api.notion.com/v1/pages/{page_id}"
        payload = {"archived": True}
        return await self._safe_request("PATCH", url, payload)

    # ============================================================
    # CLOSE SESSION
    # ============================================================
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()