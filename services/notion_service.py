import requests
import json


class NotionService:
    """
    Stable Notion API wrapper used across Evolia Backend v4 (PRO Version).

    Features:
    - Always sends Notion-Version header
    - Unified request handling
    - Clear error reporting
    - ping() for quick connectivity test
    - safe_close() for clean shutdown
    """

    BASE_URL = "https://api.notion.com/v1"
    NOTION_VERSION = "2022-06-28"

    def __init__(self, token: str):
        if not token:
            raise ValueError("❌ NOTION_API_KEY is missing.")

        self.token = token

        # Shared persistent session (fast & stable)
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Notion-Version": self.NOTION_VERSION,
            "Content-Type": "application/json"
        })

    # ------------------------------------------------------------
    # INTERNAL REQUEST HANDLER
    # ------------------------------------------------------------
    def _request(self, method: str, endpoint: str, **kwargs):
        """Unified request wrapper with robust error handling."""

        url = f"{self.BASE_URL}{endpoint}"

        try:
            response = self.session.request(method, url, **kwargs)
        except Exception as e:
            return {
                "ok": False,
                "error": f"Request error: {str(e)}",
                "endpoint": endpoint
            }

        # Try decode JSON
        try:
            data = response.json()
        except json.JSONDecodeError:
            data = {"raw": response.text}

        # Handle API errors
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
    # DATABASE METHODS
    # ------------------------------------------------------------
    def query_database(self, db_id: str, payload: dict | None = None):
        """Query a Notion database with optional filter/sort."""
        if payload is None:
            payload = {}

        return self._request(
            "POST",
            f"/databases/{db_id}/query",
            json=payload
        )

    # ------------------------------------------------------------
    # PAGE METHODS
    # ------------------------------------------------------------
    def get_page(self, page_id: str):
        return self._request("GET", f"/pages/{page_id}")

    def create_page(self, payload: dict):
        return self._request("POST", "/pages", json=payload)

    def update_page(self, page_id: str, payload: dict):
        return self._request(
            "PATCH",
            f"/pages/{page_id}",
            json=payload
        )

    # ------------------------------------------------------------
    # BLOCK METHODS
    # ------------------------------------------------------------
    def append_block_children(self, block_id: str, payload: dict):
        return self._request(
            "PATCH",
            f"/blocks/{block_id}/children",
            json=payload
        )

    # ------------------------------------------------------------
    # HEALTH CHECK
    # ------------------------------------------------------------
    def ping(self):
        """
        Quick connectivity test:
        - validates token
        - verifies headers
        - prints Notion user info
        """
        return self._request("GET", "/users/me")

    # ------------------------------------------------------------
    # CLEAN SHUTDOWN
    # ------------------------------------------------------------
    def safe_close(self):
        """Gracefully close the session."""
        try:
            self.session.close()
        except:
            pass