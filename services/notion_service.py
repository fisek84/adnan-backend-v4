import httpx
import json


class NotionService:
    """
    ASYNC Notion API wrapper for Evolia Backend v4.

    - Fully async (httpx)
    - Supports create/update/query
    - Stable error handling
    """

    BASE_URL = "https://api.notion.com/v1"
    NOTION_VERSION = "2022-06-28"

    def __init__(self, token: str):
        if not token:
            raise ValueError("❌ NOTION_API_KEY is missing.")

        self.token = token

        self.client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": self.NOTION_VERSION,
                "Content-Type": "application/json"
            },
            timeout=20.0,
        )

    # ------------------------------------------------------------
    # INTERNAL REQUEST
    # ------------------------------------------------------------
    async def _request(self, method: str, endpoint: str, **kwargs):
        url = f"{self.BASE_URL}{endpoint}"

        try:
            response = await self.client.request(method, url, **kwargs)
        except Exception as e:
            return {
                "ok": False,
                "error": f"Request error: {str(e)}",
                "endpoint": endpoint
            }

        try:
            data = response.json()
        except json.JSONDecodeError:
            data = {"raw": response.text}

        if response.status_code >= 400:
            return {
                "ok": False,
                "status": response.status_code,
                "error": data,
                "endpoint": endpoint
            }

        return {
            "ok": True,
            "status": response.status_code,
            "data": data
        }

    # ------------------------------------------------------------
    # QUERY DATABASE
    # ------------------------------------------------------------
    async def query_database(self, db_id: str, payload: dict | None = None):
        if payload is None:
            payload = {}

        return await self._request(
            "POST",
            f"/databases/{db_id}/query",
            json=payload
        )

    # ------------------------------------------------------------
    # CREATE PAGE (DATABASE ITEM)
    # ------------------------------------------------------------
    async def create_page(self, db_id: str, properties: dict):
        payload = {
            "parent": {"database_id": db_id},
            "properties": properties
        }

        return await self._request(
            "POST",
            "/pages",
            json=payload
        )

    # ------------------------------------------------------------
    # UPDATE PAGE
    # ------------------------------------------------------------
    async def update_page(self, page_id: str, properties: dict):
        payload = {"properties": properties}

        return await self._request(
            "PATCH",
            f"/pages/{page_id}",
            json=payload
        )

    # ------------------------------------------------------------
    # HEALTH CHECK
    # ------------------------------------------------------------
    async def ping(self):
        return await self._request("GET", "/users/me")

    # ------------------------------------------------------------
    # CLEAN SHUTDOWN
    # ------------------------------------------------------------
    async def close(self):
        try:
            await self.client.aclose()
        except:
            pass