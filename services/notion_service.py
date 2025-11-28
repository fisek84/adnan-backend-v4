import aiohttp
from typing import Dict, Any, Optional, List

# ============================================================
# GLOBAL REGISTRY — koristi ga tasks_service i goals_service
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
    def __init__(self, api_key: str, goals_db_id: str, tasks_db_id: str):
        self.api_key = api_key
        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id
        self.session: Optional[aiohttp.ClientSession] = None

    # ============================================================
    # SAFE SESSION
    # ============================================================
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

    # ============================================================
    # SAFE REQUEST
    # ============================================================
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

    # ============================================================
    # BASE ENDPOINTS
    # ============================================================
    async def create_page(self, payload: Dict[str, Any]):
        return await self._safe_request(
            "POST",
            "https://api.notion.com/v1/pages",
            payload
        )

    async def update_page(self, page_id: str, payload: Dict[str, Any]):
        return await self._safe_request(
            "PATCH",
            f"https://api.notion.com/v1/pages/{page_id}",
            payload
        )

    async def query_database(self, db_id: str):
        return await self._safe_request(
            "POST",
            f"https://api.notion.com/v1/databases/{db_id}/query",
            {}
        )

    async def delete_page(self, page_id: str):
        return await self._safe_request(
            "PATCH",
            f"https://api.notion.com/v1/pages/{page_id}",
            {"archived": True}
        )

    async def close(self):
        if self.session and not self.session.closed:
            await self.session.close()

    # ============================================================
    # TASKS — CREATE
    # ============================================================
    async def create_task(self, task):
        payload = {
            "parent": {"database_id": self.tasks_db_id},
            "properties": {
                "Title": {
                    "title": [{"text": {"content": task.title}}]
                },
                "Description": {
                    "rich_text": [{"text": {"content": task.description or ""}}]
                },
                "Goal": {
                    "relation": [{"id": task.goal_id}] if task.goal_id else []
                },
                "Deadline": {
                    "date": {"start": task.deadline} if task.deadline else None
                },
                "Priority": {
                    "select": {"name": task.priority} if task.priority else None
                },
                "Status": {
                    "select": {"name": task.status}
                },
                "Order": {"number": task.order},
                "Task ID": {
                    "rich_text": [{"text": {"content": task.id}}]
                }
            }
        }

        return await self.create_page(payload)

    # ============================================================
    # TASKS — UPDATE
    # ============================================================
    async def update_task(self, page_id: str, data):
        props = {}

        if data.title is not None:
            props["Title"] = {
                "title": [{"text": {"content": data.title}}]
            }

        if data.description is not None:
            props["Description"] = {
                "rich_text": [{"text": {"content": data.description}}]
            }

        if data.goal_id is not None:
            props["Goal"] = {
                "relation": [{"id": data.goal_id}] if data.goal_id else []
            }

        if data.deadline is not None:
            props["Deadline"] = {"date": {"start": data.deadline}}

        if data.priority is not None:
            props["Priority"] = {"select": {"name": data.priority}}

        if data.status is not None:
            props["Status"] = {"select": {"name": data.status}}

        return await self.update_page(page_id, {"properties": props})

    # ============================================================
    # TASKS — DELETE
    # ============================================================
    async def delete_task(self, page_id: str):
        return await self.delete_page(page_id)

    # ============================================================
    # TASKS — GET ALL
    # ============================================================
    async def get_all_tasks(self) -> List[Dict[str, Any]]:
        response = await self.query_database(self.tasks_db_id)

        if not response["ok"]:
            return []

        tasks = []
        for item in response["data"].get("results", []):
            props = item["properties"]

            tasks.append({
                "id": (
                    props["Task ID"]["rich_text"][0]["plain_text"]
                    if props["Task ID"]["rich_text"]
                    else None
                ),
                "notion_id": item["id"],
                "title": (
                    props["Title"]["title"][0]["plain_text"]
                    if props["Title"]["title"]
                    else ""
                ),
                "description": (
                    props["Description"]["rich_text"][0]["plain_text"]
                    if props["Description"]["rich_text"]
                    else ""
                ),
                "goal_id": (
                    props["Goal"]["relation"][0]["id"]
                    if props["Goal"]["relation"]
                    else None
                ),
                "deadline": (
                    props["Deadline"]["date"]["start"]
                    if props["Deadline"]["date"]
                    else None
                ),
                "priority": (
                    props["Priority"]["select"]["name"]
                    if props["Priority"]["select"]
                    else None
                ),
                "status": (
                    props["Status"]["select"]["name"]
                    if props["Status"]["select"]
                    else None
                ),
                "order": props["Order"]["number"] or 0,
            })

        return tasks