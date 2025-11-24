import httpx
import json

class NotionService:
    """
    ASYNC Notion API wrapper for Evolia Backend v4.
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

    async def _request(self, method: str, endpoint: str, **kwargs):
        url = f"{self.BASE_URL}{endpoint}"
        try:
            response = await self.client.request(method, url, **kwargs)
        except Exception as e:
            return {
                "ok": False,
                "error": f"Request error: {str(e)}",
                "endpoint": endpoint,
                "status": None,
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
                "endpoint": endpoint,
            }

        if isinstance(data, dict) and data.get("object") == "error":
            return {
                "ok": False,
                "status": response.status_code,
                "error": data,
                "endpoint": endpoint,
            }

        return {"ok": True, "status": response.status_code, "data": data}

    async def query_database(self, db_id: str, payload: dict | None = None):
        return await self._request(
            "POST",
            f"/databases/{db_id}/query",
            json=payload or {}
        )

    async def create_page(self, db_id: str, properties: dict):
        return await self._request(
            "POST",
            "/pages",
            json={"parent": {"database_id": db_id}, "properties": properties}
        )

    async def update_page(self, page_id: str, properties: dict):
        return await self._request(
            "PATCH",
            f"/pages/{page_id}",
            json={"properties": properties}
        )

    async def ping(self):
        return await self._request("GET", "/users/me")

    async def close(self):
        try:
            await self.client.aclose()
        except:
            pass