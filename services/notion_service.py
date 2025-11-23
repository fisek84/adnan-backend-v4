import httpx
import asyncio
from typing import Optional, Dict, Any, List


class NotionAPIError(Exception):
    """Generic Notion API error."""
    pass


class NotionRateLimitError(Exception):
    """Thrown when Notion returns 429."""
    def __init__(self, retry_after: float):
        self.retry_after = retry_after


class NotionService:
    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }

    async def _request(self, method: str, url: str, json: Optional[Dict] = None) -> Dict[str, Any]:
        """Centralized request handler with rate-limit + error handling."""
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(method, url, headers=self.headers, json=json)

        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 1))
            raise NotionRateLimitError(retry_after)

        if not response.is_success:
            raise NotionAPIError(f"Notion API Error {response.status_code}: {response.text}")

        return response.json()

    async def request_with_retry(self, method: str, url: str, json: Optional[Dict] = None) -> Dict[str, Any]:
        """Retries on rate-limit, clean and safe for sync loops."""
        while True:
            try:
                return await self._request(method, url, json=json)
            except NotionRateLimitError as e:
                await asyncio.sleep(e.retry_after)

    # -------------------------------------------------------------
    #        PUBLIC METHODS (clean, stable, ready for sync)
    # -------------------------------------------------------------

    async def get_page(self, page_id: str) -> Dict[str, Any]:
        url = f"{self.base_url}/pages/{page_id}"
        return await self.request_with_retry("GET", url)

    async def update_page(self, page_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/pages/{page_id}"
        payload = {"properties": properties}
        return await self.request_with_retry("PATCH", url, payload)

    async def create_page(self, db_id: str, properties: Dict[str, Any]) -> Dict[str, Any]:
        url = f"{self.base_url}/pages"
        payload = {
            "parent": {"database_id": db_id},
            "properties": properties
        }
        return await self.request_with_retry("POST", url, payload)

    async def query_database(
        self,
        db_id: str,
        filter: Optional[Dict] = None,
        sorts: Optional[List[Dict]] = None,
        page_size: int = 100
    ) -> Dict[str, Any]:
        """Flexible DB query with optional filter + sorting + pagination."""
        url = f"{self.base_url}/databases/{db_id}/query"
        payload = {"page_size": page_size}

        if filter:
            payload["filter"] = filter
        if sorts:
            payload["sorts"] = sorts

        return await self.request_with_retry("POST", url, payload)