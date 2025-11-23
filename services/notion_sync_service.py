from typing import Any, Dict, List, Optional
import asyncio

from services.notion_service import NotionService
from services.goals_service import GoalsService
from services.tasks_service import TasksService


class NotionSyncService:
    """
    Sync layer for Notion ↔ Backend.
    Supports:
    - Goals sync (up/down)
    - Tasks sync (up/down)
    - Debounced automatic sync (UP)
    """

    def __init__(
        self,
        notion_service: NotionService,
        goals_service: GoalsService,
        tasks_service: TasksService,
        goals_db_id: str,
        tasks_db_id: str
    ):
        self.notion = notion_service
        self.goals = goals_service
        self.tasks = tasks_service
        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id

        # debounce
        self._goals_db_task: Optional[asyncio.Task] = None
        self._tasks_db_task: Optional[asyncio.Task] = None
        self._debounce_delay = 0.3  # 300 ms

    # ============================================================
    # DEBOUNCE SYNC UP
    # ============================================================
    async def debounce_goals_sync(self):
        if self._goals_db_task:
            self._goals_db_task.cancel()
        self._goals_db_task = asyncio.create_task(self._debounce_goals())

    async def _debounce_goals(self):
        try:
            await asyncio.sleep(self._debounce_delay)
            await self.sync_goals_up()
        except asyncio.CancelledError:
            pass

    async def debounce_tasks_sync(self):
        if self._tasks_db_task:
            self._tasks_db_task.cancel()
        self._tasks_db_task = asyncio.create_task(self._debounce_tasks())

    async def _debounce_tasks(self):
        try:
            await asyncio.sleep(self._debounce_delay)
            await self.sync_tasks_up()
        except asyncio.CancelledError:
            pass

    # ============================================================
    # SYNC DOWN (Notion → Backend)
    # ============================================================
    async def sync_goals_down(self) -> None:
        pages = await self.fetch_all_pages(self.goals_db_id)
        for page in pages:
            mapped = self.map_notion_goal_to_local(page)
            self.goals.sync_from_notion(mapped)

    async def sync_tasks_down(self) -> None:
        pages = await self.fetch_all_pages(self.tasks_db_id)
        for page in pages:
            mapped = self.map_notion_task_to_local(page)
            self.tasks.sync_from_notion(mapped)

    # ============================================================
    # SYNC UP (Backend → Notion)
    # ============================================================
    async def sync_goals_up(self) -> None:
        all_goals = self.goals.get_all()

        for goal in all_goals:
            goal_dict = self.goals.to_dict(goal)
            notion_props = self.map_local_goal_to_notion(goal_dict)

            try:
                await self.notion.update_page(goal.id, notion_props)
                continue
            except Exception:
                pass

            await self.notion.create_page(self.goals_db_id, notion_props)

    async def sync_tasks_up(self) -> None:
        all_tasks = self.tasks.get_all()

        for task in all_tasks:
            task_dict = {
                "id": task.id,
                "name": task.title,
                "description": task.description,
                "goal": [task.goal_id] if task.goal_id else [],
                "due_date": task.deadline,
                "priority": task.priority,
                "status": task.status,
                "order": 0,
            }

            notion_props = self.map_local_task_to_notion(task_dict)

            try:
                await self.notion.update_page(task.id, notion_props)
                continue
            except Exception:
                pass

            await self.notion.create_page(self.tasks_db_id, notion_props)

    # ============================================================
    # HELPERS
    # ============================================================
    async def fetch_all_pages(self, db_id: str) -> List[Dict[str, Any]]:
        results = []
        cursor = None

        while True:
            response = await self.notion.query_database(
                db_id=db_id,
                filter=None
            )

            results.extend(response.get("results", []))

            if not response.get("has_more"):
                break

            cursor = response.get("next_cursor")

        return results

    def get_page_id(self, page: Dict[str, Any]) -> str:
        return page.get("id", "")

    def get_properties(self, page: Dict[str, Any]) -> Dict[str, Any]:
        return page.get("properties", {})

    # ============================================================
    # UNIVERSAL PARSERS
    # ============================================================
    def _get_text(self, props, field):
        try:
            return props[field]["title"][0]["plain_text"]
        except:
            return ""

    def _get_rich(self, props, field):
        try:
            return props[field]["rich_text"][0]["plain_text"]
        except:
            return ""

    def _get_select(self, props, field):
        try:
            return props[field]["select"]["name"]
        except:
            return None

    def _get_number(self, props, field):
        try:
            return props[field]["number"]
        except:
            return 0

    def _get_date(self, props, field):
        try:
            return props[field]["date"]["start"]
        except:
            return None

    def _get_rels(self, props, field):
        try:
            return [rel["id"] for rel in props[field]["relation"]]
        except:
            return []

    # ============================================================
    # MAPPING — GOALS
    # ============================================================
    def map_notion_goal_to_local(self, page: Dict[str, Any]) -> Dict[str, Any]:
        props = self.get_properties(page)

        return {
            "id": self.get_page_id(page),
            "name": self._get_text(props, "Name"),
            "type": self._get_select(props, "Type"),
            "status": self._get_select(props, "Status"),
            "auto_status": self._get_select(props, "Auto Status"),
            "deadline": self._get_date(props, "Deadline"),
            "progress": self._get_number(props, "Progress"),
            "parent_goal": self._get_rels(props, "Parent Goal"),
            "child_goals": self._get_rels(props, "Child Goals"),
            "description": self._get_rich(props, "Description"),
        }

    def map_local_goal_to_notion(self, goal: Dict[str, Any]) -> Dict[str, Any]:
        def text(v): return [{"type": "text", "text": {"content": v or ""}}]
        def select(v): return {"name": v} if v else None
        def rel(ids): return [{"id": x} for x in ids] if ids else []

        props = {
            "Name": {"title": text(goal.get("name", ""))},
            "Type": {"select": select(goal.get("type"))},
            "Status": {"select": select(goal.get("status"))},
            "Auto Status": {"select": select(goal.get("auto_status"))},
            "Deadline": (
                {"date": {"start": goal.get("deadline")}}
                if goal.get("deadline") else None
            ),
            "Progress": {"number": goal.get("progress", 0)},
            "Parent Goal": {"relation": rel(goal.get("parent_goal", []))},
            "Child Goals": {"relation": rel(goal.get("child_goals", []))},
            "Description": {"rich_text": text(goal.get("description", ""))}
        }

        return {k: v for k, v in props.items() if v is not None}

    # ============================================================
    # MAPPING — TASKS
    # ============================================================
    def map_notion_task_to_local(self, page: Dict[str, Any]) -> Dict[str, Any]:
        props = self.get_properties(page)

        return {
            "id": self.get_page_id(page),
            "name": self._get_text(props, "Name"),
            "status": self._get_select(props, "Status"),
            "priority": self._get_select(props, "Priority"),
            "due_date": self._get_date(props, "Due Date"),
            "goal": self._get_rels(props, "Goal"),
            "order": self._get_number(props, "Order"),
            "description": self._get_rich(props, "Description"),
        }

    def map_local_task_to_notion(self, task: Dict[str, Any]) -> Dict[str, Any]:
        def text(v): return [{"type": "text", "text": {"content": v or ""}}]
        def select(v): return {"name": v} if v else None
        def rel(ids): return [{"id": x} for x in ids] if ids else []

        props = {
            "Name": {"title": text(task.get("name", ""))},
            "Status": {"select": select(task.get("status"))},
            "Priority": {"select": select(task.get("priority"))},
            "Due Date": (
                {"date": {"start": task.get("due_date")}}
                if task.get("due_date") else None
            ),
            "Goal": {"relation": rel(task.get("goal", []))},
            "Order": {"number": task.get("order", 0)},
            "Description": {"rich_text": text(task.get("description", ""))}
        }

        return {k: v for k, v in props.items() if v is not None}