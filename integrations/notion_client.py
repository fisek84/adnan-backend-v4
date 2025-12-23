import httpx
import asyncio
from typing import Any, Optional, Dict, List


class NotionClientError(Exception):
    """General Notion API exception."""

    pass


class NotionRateLimitError(Exception):
    """Raised when Notion returns HTTP 429."""

    def __init__(self, retry_after: float):
        self.retry_after = retry_after


class NotionClient:
    """
    Minimalistic but powerful Notion client wrapper.
    Designed for Evolia backend (high reliability, async operations).
    """

    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json",
        }

    # ---------------------------------------------------------
    # INTERNAL REQUEST LAYER
    # ---------------------------------------------------------

    async def _request(
        self, method: str, endpoint: str, json: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Low-level request wrapper with error handling."""
        url = f"{self.base_url}{endpoint}"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method, url, headers=self.headers, json=json
            )

        # Handle rate limit
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", 1))
            raise NotionRateLimitError(retry_after)

        # Handle other errors
        if not response.is_success:
            raise NotionClientError(
                f"Notion API Error {response.status_code}: {response.text}"
            )

        return response.json()

    async def _request_with_retry(
        self, method: str, endpoint: str, json: Optional[Dict] = None
    ) -> Dict[str, Any]:
        """Retries the request automatically on rate-limit."""
        while True:
            try:
                return await self._request(method, endpoint, json=json)
            except NotionRateLimitError as e:
                await asyncio.sleep(e.retry_after)

    # ---------------------------------------------------------
    # PUBLIC API (READY FOR SYNC ENGINE)
    # ---------------------------------------------------------

    async def get_page(self, page_id: str) -> Dict[str, Any]:
        return await self._request_with_retry("GET", f"/pages/{page_id}")

    async def update_page(
        self, page_id: str, properties: Dict[str, Any]
    ) -> Dict[str, Any]:
        payload = {"properties": properties}
        return await self._request_with_retry("PATCH", f"/pages/{page_id}", payload)

    async def create_page(
        self, database_id: str, properties: Dict[str, Any]
    ) -> Dict[str, Any]:
        payload = {"parent": {"database_id": database_id}, "properties": properties}
        return await self._request_with_retry("POST", "/pages", payload)

    async def query_database(
        self,
        database_id: str,
        filter: Optional[Dict] = None,
        sorts: Optional[List[Dict]] = None,
        page_size: int = 100,
    ) -> Dict[str, Any]:
        """Query a Notion DB with filter, sorts and pagination."""
        payload = {"page_size": page_size}
        if filter:
            payload["filter"] = filter
        if sorts:
            payload["sorts"] = sorts

        return await self._request_with_retry(
            "POST", f"/databases/{database_id}/query", payload
        )
