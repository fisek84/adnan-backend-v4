import httpx
import asyncio
from typing import Optional, Dict, Any, List


# ============================================================
#   CUSTOM ERRORS
# ============================================================
class NotionAPIError(Exception):
    """Generic Notion API error."""
    pass


class NotionRateLimitError(Exception):
    """Thrown when Notion returns 429."""
    def __init__(self, retry_after: float):
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded. Retry after {retry_after} seconds.")


# ============================================================
#   NOTION SERVICE (PRO VERSION)
# ============================================================
class NotionService:
    """
    Evolia NotionService v3.0 (PRO)
    ----------------------------------------------
    Poboljšanja:
    ✔ Automatski retry
    ✔ Detaljan error handling
    ✔ Stabilno ponašanje kod rate-limit-a
    ✔ Bolji timeout + konekcijski pool
    ✔ Kompatibilno sa Render/Docker okruženjem
    ✔ Otporno na flaky network situacije
    ✔ Query sa cursor podrškom

    Ključ infrastrukture za Notion sync.
    """

    def __init__(self, token: str):
        self.token = token
        self.base_url = "https://api.notion.com/v1"
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Notion-Version": "2022-06-28",
            "Content-Type": "application/json"
        }

        # Shared HTTP client — brže, stabilnije, manje troši resurse
        self.client = httpx.AsyncClient(
            timeout=20,
            limits=httpx.Limits(
                max_keepalive_connections=20,
                max_connections=40,
            )
        )

    # ============================================================
    #   LOW-LEVEL REQUEST
    # ============================================================
    async def _request(self, method: str, url: str, json: Optional[Dict] = None) -> Dict[str, Any]:
        """
        Internal request handler with:
        - rate limit detection
        - stable error handling
        """

        response = await self.client.request(
            method,
            url,
            headers=self.headers,
            json=json
        )

        # RATE LIMIT
        if response.status_code == 429:
            retry_after = float(response.headers.get("Retry-After", "1"))
            raise NotionRateLimitError(retry_after)

        # ERROR HANDLING
        if not response.is_success:
            raise NotionAPIError(
                f"Notion API Error {response.status_code}: {response.text}"
            )

        return response.json()

    # ============================================================
    #   HIGH-LEVEL RETRY WRAPPER
    # ============================================================
    async def request_with_retry(
        self,
        method: str,
        url: str,
        json: Optional[Dict] = None,
        retries: int = 3
    ) -> Dict[str, Any]:

        """
        Handles:
        - rate limits
        - transient failures
        - retry logic
        """

        attempt = 0

        while attempt < retries:
            try:
                return await self._request(method, url, json=json)

            except NotionRateLimitError as e:
                await asyncio.sleep(e.retry_after)

            except (httpx.ConnectError, httpx.ReadTimeout):
                # exponential backoff
                await asyncio.sleep(1.5 * (attempt + 1))

            except Exception:
                if attempt == retries - 1:
                    raise
                await asyncio.sleep(0.5)

            attempt += 1

        raise NotionAPIError("Max retries reached.")

    # ============================================================
    #            PUBLIC NOTION OPERATIONS
    # ============================================================

    # ----------  PAGE CONTROL  ----------
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

    # ----------  DATABASE QUERY  ----------
    async def query_database(
        self,
        db_id: str,
        filter: Optional[Dict] = None,
        sorts: Optional[List[Dict]] = None,
        page_size: int = 100,
        cursor: Optional[str] = None
    ) -> Dict[str, Any]:

        url = f"{self.base_url}/databases/{db_id}/query"

        payload = {
            "page_size": page_size
        }

        if filter:
            payload["filter"] = filter
        if sorts:
            payload["sorts"] = sorts
        if cursor:
            payload["start_cursor"] = cursor

        return await self.request_with_retry("POST", url, payload)

    # ============================================================
    #   CLEANUP (for controlled shutdown)
    # ============================================================
    async def close(self):
        await self.client.aclose()