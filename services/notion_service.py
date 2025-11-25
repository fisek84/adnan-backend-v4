import aiohttp
import asyncio
from typing import Dict, Any, Optional


class NotionService:
    def __init__(self, token: str):
        self.token = token
        self.session: Optional[aiohttp.ClientSession] = None

    # ============================================================
    # LAZY SESSION (STABLE FOR RENDER)
    # ============================================================
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                    "Notion-Version": "2022-06-28",
                }
            )
        return self.session

    # ============================================================
    # GENERIC REQUEST HANDLER
    # ============================================================
    async def _request(self, method: str, url: str, payload: Optional[Dict] = None):
        session = await self._get_session()

        try:
            async with session.request(method, url, json=payload) as resp:
                data = await resp.json()

                return {
                    "ok": resp.status < 300,
                    "status": resp.status,
                    "data": data,
                }
        except Exception as e:
            return {
                "ok": False,
                "error": str(e),
                "status": 500,
            }

    # ============================================================
    # CREATE PAGE
    # ============================================================
    async def create_page(self, db_id: str, props: Dict[str, Any]):
        url = "https://api.notion.com/v1/pages"
        payload = {
            "parent": {"database_id": db_id},
            "properties": props,
        }
        return await self._request("POST", url, payload)

    # ============================================================
    # UPDATE PAGE
    # ============================================================
    async def update_page(self, page_id: str, props: Dict[str, Any]):
        url = f"https://api.notion.com/v1/pages/{page_id}"
        payload = {"properties": props}
        return await self._request("PATCH", url, payload)

    # ============================================================
    # QUERY DATABASE
    # ============================================================
    async def query_database(self, db_id: str):
        url = f"https://api.notion.com/v1/databases/{db_id}/query"
        return await self._request("POST", url)

    # ============================================================
    # CLOSE SESSION
    # ============================================================
    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()