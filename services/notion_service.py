# services/notion_service.py

import aiohttp
from typing import Dict, Any, Optional, List
import logging  # Dodajemo logovanje

# ============================================================
# GLOBAL REGISTRY
# ============================================================
_global_notion_service = None

def set_notion_service(instance):
    global _global_notion_service
    _global_notion_service = instance

def get_notion_service():
    if _global_notion_service is None:
        raise RuntimeError("NotionService has not been initialized yet.")
    return _global_notion_service

# ============================================================
# MAIN NOTION SERVICE
# ============================================================
class NotionService:
    def __init__(
        self,
        api_key: str,
        goals_db_id: str,
        tasks_db_id: str,
        projects_db_id: str,
        active_goals_db_id: str = None,
        agent_exchange_db_id: str = None,
        agent_projects_db_id: str = None,
        ai_weekly_summary_db_id: str = None,
        blocked_goals_db_id: str = None,
        completed_goals_db_id: str = None,
        lead_db_id: str = None,
        kpi_db_id: str = None,
        flp_db_id: str = None
    ):
        self.api_key = api_key
        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id
        self.projects_db_id = projects_db_id

        # dodatne baze
        self.active_goals_db_id = active_goals_db_id
        self.agent_exchange_db_id = agent_exchange_db_id
        self.agent_projects_db_id = agent_projects_db_id
        self.ai_weekly_summary_db_id = ai_weekly_summary_db_id
        self.blocked_goals_db_id = blocked_goals_db_id
        self.completed_goals_db_id = completed_goals_db_id
        self.lead_db_id = lead_db_id
        self.kpi_db_id = kpi_db_id
        self.flp_db_id = flp_db_id

        self.session: Optional[aiohttp.ClientSession] = None

        # Inicijalizujemo logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

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

    async def _safe_request(self, method: str, url: str, payload: Dict[str, Any] = None):
        session = await self._get_session()
        try:
            async with session.request(method, url, json=payload) as response:
                if response.status not in (200, 201):
                    self.logger.error(f"Notion API Error - Status: {response.status}, URL: {url}")
                    return {
                        "ok": False,
                        "status": response.status,
                        "error": await response.text()
                    }
                self.logger.info(f"Notion API Success - Status: {response.status}, URL: {url}")
                return {
                    "ok": True,
                    "status": response.status,
                    "data": await response.json()
                }
        except Exception as e:
            self.logger.error(f"Exception during Notion API request: {str(e)}")
            return {"ok": False, "status": 500, "error": str(e)}

    # ============================================================
    # CORE HTTP WRAPPERS
    # ============================================================
    async def create_page(self, payload: Dict[str, Any]):
        self.logger.info("Creating page in Notion...")
        return await self._safe_request("POST", "https://api.notion.com/v1/pages", payload)

    async def update_page(self, page_id: str, payload: Dict[str, Any]):
        self.logger.info(f"Updating page in Notion: {page_id}")
        return await self._safe_request("PATCH", f"https://api.notion.com/v1/pages/{page_id}", payload)

    async def query_database(self, db_id: str, filter_payload=None):
        self.logger.info(f"Querying database in Notion: {db_id}")
        return await self._safe_request(
            "POST",
            f"https://api.notion.com/v1/databases/{db_id}/query",
            filter_payload or {}
        )

    # ============================================================
    # TASKS — CREATE
    # ============================================================
    async def create_task(self, task):
        self.logger.info(f"Creating task in Notion: {task.title}")
        props = {
            "Name": {"title": [{"text": {"content": task.title}}]},
            "Description": {"rich_text": [{"text": {"content": task.description or ""}}]},
            "Status": {"select": {"name": task.status}},
            "Order": {"number": task.order},
            "Task ID": {"rich_text": [{"text": {"content": task.id}}]}
        }

        if task.goal_id:
            props["Goal"] = {"relation": [{"id": task.goal_id}]}
        if task.deadline:
            props["Due Date"] = {"date": {"start": task.deadline}}
        if task.priority:
            props["Priority"] = {"select": {"name": task.priority}}

        payload = {
            "parent": {"database_id": self.tasks_db_id},
            "properties": props
        }

        response = await self.create_page(payload)
        
        # Log response
        if response["ok"]:
            notion_page_id = response["data"]["id"]
            self.logger.info(f"Task created successfully in Notion with ID: {notion_page_id}")
        else:
            self.logger.error(f"Failed to create task in Notion: {response['error']}")

        # VAŽNO: uvijek vraćamo standardizirani dict (ok / data / error)
        return response
