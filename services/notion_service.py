# services/notion_service.py

import aiohttp
from typing import Dict, Any, Optional
import logging
from datetime import datetime


class NotionService:
    """
    CANONICAL NOTION SERVICE

    - ČIST EXECUTOR
    - prima AICommand
    - mapira intent → Notion API
    - JEDINA write tačka prema Notionu
    """

    def __init__(
        self,
        api_key: str,
        goals_db_id: str,
        tasks_db_id: str,
        projects_db_id: str,
    ):
        self.api_key = api_key
        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id
        self.projects_db_id = projects_db_id

        self.session: Optional[aiohttp.ClientSession] = None
        self.logger = logging.getLogger(__name__)

        self.knowledge_snapshot: Dict[str, Any] = {
            "last_sync": None,
            "goals": [],
            "tasks": [],
            "projects": [],
        }

    # --------------------------------------------------
    # SESSION
    # --------------------------------------------------

    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Notion-Version": "2022-06-28",
                }
            )
        return self.session

    async def _safe_request(self, method: str, url: str, payload=None):
        session = await self._get_session()
        async with session.request(method, url, json=payload) as response:
            text = await response.text()
            if response.status not in (200, 201, 202):
                raise RuntimeError(f"Notion API error {response.status}: {text}")
            return await response.json() if text else {}

    # --------------------------------------------------
    # EXECUTION ENTRY POINT (WRITE)
    # --------------------------------------------------

    async def execute(self, command) -> Dict[str, Any]:
        """
        Jedina ulazna tačka za write akcije.
        """

        if command.intent == "create_goal":
            name = command.params.get("name")
            if not name:
                raise RuntimeError("Missing goal name")

            payload = {
                "parent": {"database_id": self.goals_db_id},
                "properties": {
                    "Name": {
                        "title": [
                            {
                                "text": {
                                    "content": name
                                }
                            }
                        ]
                    }
                },
            }

            result = await self._safe_request(
                "POST",
                "https://api.notion.com/v1/pages",
                payload,
            )

            return {
                "success": True,
                "notion_page_id": result.get("id"),
            }

        raise RuntimeError(f"Unsupported intent: {command.intent}")

    # --------------------------------------------------
    # READ-ONLY SNAPSHOT
    # --------------------------------------------------

    async def sync_knowledge_snapshot(self):
        self.logger.info(">> Syncing Notion knowledge snapshot")
        self.knowledge_snapshot["last_sync"] = datetime.utcnow().isoformat()
        return {"ok": True}

    def get_knowledge_snapshot(self) -> Dict[str, Any]:
        return dict(self.knowledge_snapshot)


# --------------------------------------------------
# SINGLETON (KANONSKI)
# --------------------------------------------------

_NOTION_SERVICE_SINGLETON: Optional[NotionService] = None


def set_notion_service(service: NotionService) -> None:
    global _NOTION_SERVICE_SINGLETON
    _NOTION_SERVICE_SINGLETON = service


def get_notion_service() -> NotionService:
    if _NOTION_SERVICE_SINGLETON is None:
        raise RuntimeError("NotionService not initialized")
    return _NOTION_SERVICE_SINGLETON
