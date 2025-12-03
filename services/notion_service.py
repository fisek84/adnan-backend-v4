import aiohttp
from typing import Dict, Any, Optional, List

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
                    return {
                        "ok": False,
                        "status": response.status,
                        "error": await response.text()
                    }
                return {
                    "ok": True,
                    "status": response.status,
                    "data": await response.json()
                }
        except Exception as e:
            return {"ok": False, "status": 500, "error": str(e)}

    async def create_page(self, payload: Dict[str, Any]):
        return await self._safe_request("POST", "https://api.notion.com/v1/pages", payload)

    async def update_page(self, page_id: str, payload: Dict[str, Any]):
        return await self._safe_request("PATCH", f"https://api.notion.com/v1/pages/{page_id}", payload)

    async def query_database(self, db_id: str, filter_payload=None):
        return await self._safe_request("POST", f"https://api.notion.com/v1/databases/{db_id}/query", filter_payload or {})

    async def delete_page(self, page_id: str):
        return await self._safe_request("PATCH", f"https://api.notion.com/v1/pages/{page_id}", {"archived": True})

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    async def get_all_pages(self, db_id: str):
        res = await self.query_database(db_id)
        if not res["ok"]:
            return []
        return res["data"].get("results", [])

    async def _resolve_page_id(self, internal_task_id: str) -> Optional[str]:
        filter_payload = {
            "filter": {
                "property": "Task ID",
                "rich_text": {"equals": internal_task_id}
            }
        }
        res = await self.query_database(self.tasks_db_id, filter_payload)
        if not res["ok"]:
            return None
        results = res["data"].get("results", [])
        if len(results) == 0:
            return None
        return results[0]["id"]

    # ============================================================
    # TASKS — CREATE
    # ============================================================
    async def create_task(self, task):
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
        return await self.create_page(payload)

    async def update_task(self, page_id: str, data):
        if len(page_id) != 36 or "-" not in page_id:
            resolved = await self._resolve_page_id(page_id)
            if resolved:
                page_id = resolved

        props = {}

        if data.title is not None:
            props["Name"] = {"title": [{"text": {"content": data.title}}]}
        if data.description is not None:
            props["Description"] = {"rich_text": [{"text": {"content": data.description}}]}
        if data.goal_id is not None:
            props["Goal"] = {"relation": [{"id": data.goal_id}] if data.goal_id else []}
        if data.deadline is not None:
            props["Due Date"] = {"date": {"start": data.deadline}}
        if data.priority is not None:
            props["Priority"] = {"select": {"name": data.priority}}
        if data.status is not None:
            props["Status"] = {"select": {"name": data.status}}

        return await self.update_page(page_id, {"properties": props})

    async def get_all_tasks(self) -> List[Dict[str, Any]]:
        response = await self.query_database(self.tasks_db_id)
        if not response["ok"]:
            return []

        tasks = []
        for item in response["data"].get("results", []):
            props = item["properties"]
            tasks.append({
                "id": props["Task ID"]["rich_text"][0]["plain_text"] if props["Task ID"]["rich_text"] else None,
                "notion_id": item["id"],
                "title": props["Name"]["title"][0]["plain_text"] if props["Name"]["title"] else "",
                "description": props["Description"]["rich_text"][0]["plain_text"] if props["Description"]["rich_text"] else "",
                "goal_id": props["Goal"]["relation"][0]["id"] if props["Goal"]["relation"] else None,
                "deadline": props["Due Date"]["date"]["start"] if props["Due Date"].get("date") else None,
                "priority": props["Priority"]["select"]["name"] if props["Priority"]["select"] else None,
                "status": props["Status"]["select"]["name"] if props["Status"]["select"] else None,
                "order": props["Order"]["number"] or 0,
            })

        return tasks

    # ============================================================
    # PROJECTS — CREATE
    # ============================================================
    async def create_project(self, project):
        props = {
            "Name": {"title": [{"text": {"content": project.title}}]},
            "Description": {"rich_text": [{"text": {"content": project.description or ""}}]},
            "Status": {"select": {"name": project.status}},
            "Project ID": {"rich_text": [{"text": {"content": project.id}}]}
        }

        if project.deadline:
            props["Deadline"] = {"date": {"start": project.deadline}}
        if project.start_date:
            props["Start Date"] = {"date": {"start": project.start_date}}
        if project.priority:
            props["Priority"] = {"select": {"name": project.priority}}
        if project.project_type:
            props["Project Type"] = {"select": {"name": project.project_type}}
        if project.goal_id:
            props["Goal"] = {"relation": [{"id": project.goal_id}]}

        payload = {
            "parent": {"database_id": self.projects_db_id},
            "properties": props
        }

        return await self.create_page(payload)
