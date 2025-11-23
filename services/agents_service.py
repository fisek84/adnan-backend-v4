import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional


class AgentsService:
    """
    Evolia AgentsService v3.0 (PRO)
    ------------------------------------------------------------
    Modul za komunikaciju između AI agenata, backend sistema i
    Notion Agent Exchange + Projects baza.

    Poboljšanja:
    ✔ async/await za stabilne Notion operacije
    ✔ standardizovan output
    ✔ robustan error handling
    ✔ timestamp u UTC
    ✔ helper funkcije za sve česte operacije
    ✔ shortName generator za dug sadržaj
    ✔ project lifecycle podrška
    """

    def __init__(self, notion_token: str, exchange_db_id: str, projects_db_id: str):
        from notion_client import AsyncClient
        self.notion = AsyncClient(auth=notion_token)

        self.exchange_db = exchange_db_id
        self.projects_db = projects_db_id

    # ============================================================
    # INTERNAL UTILS
    # ============================================================
    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _truncate(text: str, length: int = 50) -> str:
        return text if len(text) <= length else text[:47] + "..."

    # ============================================================
    # NOTION SAFE WRAPPER
    # ============================================================
    async def _safe_notion(self, method: str, *args, **kwargs):
        """
        Safe call wrapper — backend nikad ne puca.
        """
        try:
            fn = getattr(self.notion, method)
            return await fn(*args, **kwargs)
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "method": method
            }

    # ============================================================
    # 1. POST MESSAGE (Agent Exchange DB)
    # ============================================================
    async def post_message(self, agent: str, content: str,
                           msg_type: str = "message") -> Dict[str, Any]:

        short_title = self._truncate(content)

        payload = {
            "parent": {"database_id": self.exchange_db},
            "properties": {
                "Name": {"title": [{"text": {"content": short_title}}]},
                "Sender": {"select": {"name": agent}},
                "Recipient": {"select": {"name": "System"}},
                "Type": {"select": {"name": msg_type}},
                "Content": {"rich_text": [{"text": {"content": content}}]},
                "Timestamp": {"date": {"start": self._now()}}
            }
        }

        result = await self._safe_notion("pages.create", **payload)

        return {
            "status": "success" if "id" in result else "error",
            "page_id": result.get("id"),
            "payload": payload,
            "notion_result": result
        }

    # ============================================================
    # 2. READ MESSAGES
    # ============================================================
    async def read_messages(self, limit: int = 20) -> List[Dict[str, Any]]:
        query = await self._safe_notion(
            "databases.query",
            database_id=self.exchange_db,
            page_size=limit,
            sorts=[{"property": "Timestamp", "direction": "descending"}]
        )

        if query.get("status") == "error":
            return [query]

        return query.get("results", [])

    # ============================================================
    # 3. CREATE PROJECT
    # ============================================================
    async def create_project(self, agent: str, project_title: str,
                             description: str = "") -> Dict[str, Any]:

        short_title = self._truncate(project_title)

        payload = {
            "parent": {"database_id": self.projects_db},
            "properties": {
                "Name": {"title": [{"text": {"content": short_title}}]},
                "Agent": {"select": {"name": agent}},
                "Description": {"rich_text": [{"text": {"content": description}}]},
                "Status": {"select": {"name": "Active"}},
                "Created": {"date": {"start": self._now()}}
            }
        }

        result = await self._safe_notion("pages.create", **payload)

        return {
            "status": "success" if "id" in result else "error",
            "project_id": result.get("id"),
            "payload": payload,
            "notion_result": result
        }

    # ============================================================
    # 4. UPDATE AGENT STATE
    # ============================================================
    async def update_agent_state(self, agent: str, new_state: str) -> Dict[str, Any]:

        title = f"{agent} — state update"

        payload = {
            "parent": {"database_id": self.exchange_db},
            "properties": {
                "Name": {"title": [{"text": {"content": title}}]},
                "Sender": {"select": {"name": agent}},
                "Recipient": {"select": {"name": "System"}},
                "Type": {"select": {"name": "state"}},
                "Content": {"rich_text": [{"text": {"content": new_state}}]},
                "Timestamp": {"date": {"start": self._now()}}
            }
        }

        result = await self._safe_notion("pages.create", **payload)

        return {
            "status": "success" if "id" in result else "error",
            "state": new_state,
            "page_id": result.get("id"),
            "payload": payload
        }

    # ============================================================
    # 5. PROJECT STATUS UPDATE
    # ============================================================
    async def update_project_status(self, project_id: str,
                                    status: str) -> Dict[str, Any]:

        payload = {
            "properties": {
                "Status": {"select": {"name": status}},
                "Updated": {"date": {"start": self._now()}}
            }
        }

        result = await self._safe_notion(
            "pages.update",
            page_id=project_id,
            **payload
        )

        return {
            "status": "success" if "id" in result else "error",
            "new_status": status,
            "notion_result": result
        }

    # ============================================================
    # 6. SERVICE STATUS
    # ============================================================
    async def status(self) -> Dict[str, Any]:
        """
        Health check za AgentsService.
        """
        return {
            "service": "agents_service",
            "exchange_db": self.exchange_db,
            "projects_db": self.projects_db,
            "time": self._now(),
        }