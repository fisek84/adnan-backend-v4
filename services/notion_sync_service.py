import asyncio
from typing import Any, Dict, List, Optional


class NotionSyncService:
    """
    Evolia NotionSyncService v3.0
    --------------------------------------------------------
    Profesionalna verzija:
    - Safe debounce (bez race condition-a)
    - Stabilan sync up/down
    - Exception handling (ne ruši backend)
    - Otpornost na nepotpune Notion podatke
    - Stabilan mapping Goals / Tasks
    """

    def __init__(
        self,
        notion_service,
        goals_service,
        tasks_service,
        goals_db_id: str,
        tasks_db_id: str
    ):
        self.notion = notion_service
        self.goals = goals_service
        self.tasks = tasks_service
        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id

        # debounce tasks
        self._goals_db_task: Optional[asyncio.Task] = None
        self._tasks_db_task: Optional[asyncio.Task] = None
        self._debounce_delay = 0.25  # 250 ms

    # ============================================================
    # INTERNAL: DEBOUNCE HELPERS
    # ============================================================
    async def debounce_goals_sync(self):
        self._cancel(self._goals_db_task)
        self._goals_db_task = asyncio.create_task(self._debounce(self.sync_goals_up))

    async def debounce_tasks_sync(self):
        self._cancel(self._tasks_db_task)
        self._tasks_db_task = asyncio.create_task(self._debounce(self.sync_tasks_up))

    async def _debounce(self, fn):
        try:
            await asyncio.sleep(self._debounce_delay)
            await fn()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[NotionSyncService] Debounce error: {e}")

    @staticmethod
    def _cancel(task: Optional[asyncio.Task]):
        if task and not task.done():
            task.cancel()

    # ============================================================
    # SYNC DOWN (NOTION → LOCAL)
    # ============================================================
    async def sync_goals_down(self) -> None:
        try:
            pages = await self._fetch_all(self.goals_db_id)
            for page in pages:
                mapped = self.map_notion_goal_to_local(page)
                self.goals.sync_from_notion(mapped)
        except Exception as e:
            print(f"[NotionSyncService] sync_goals_down error: {e}")

    async def sync_tasks_down(self) -> None:
        try:
            pages = await self._fetch_all(self.tasks_db_id)
            for page in pages:
                mapped = self.map_notion_task_to_local(page)
                self.tasks.sync_from_notion(mapped)
        except Exception as e:
            print(f"[NotionSyncService] sync_tasks_down error: {e}")

    # ============================================================
    # SYNC UP (LOCAL → NOTION)
    # ============================================================
    async def sync_goals_up(self) -> None:
        goals = self.goals.get_all()

        for goal in goals:
            goal_dict = self.goals.to_dict(goal)
            data = self.map_local_goal_to_notion(goal_dict)

            try:
                await self.notion.update_page(goal.id, data)
            except Exception:
                try:
                    await self.notion.create_page(self.goals_db_id, data)
                except Exception as e:
                    print(f"[NotionSyncService] sync_goals_up create error: {e}")

    async def sync_tasks_up(self) -> None:
        tasks = self.tasks.get_all()

        for task in tasks:
            task_dict = self._task_to_dict(task)
            data = self.map_local_task_to_notion(task_dict)

            try:
                await self.notion.update_page(task.id, data)
            except Exception:
                try:
                    await self.notion.create_page(self.tasks_db_id, data)
                except Exception as e:
                    print(f"[NotionSyncService] sync_tasks_up create error: {e}")

    # ============================================================
    # HELPERS
    # ============================================================
    async def _fetch_all(self, db_id: str) -> List[Dict[str, Any]]:
        results = []
        cursor = None

        while True:
            try:
                response = await self.notion.query_database(
                    db_id=db_id,
                    filter=None,
                    cursor=cursor
                )
            except Exception as e:
                print(f"[NotionSyncService] query error: {e}")
                break

            results.extend(response.get("results", []))

            if not response.get("has_more"):
                break

            cursor = response.get("next_cursor")

        return results

    def _task_to_dict(self, task):
        return {
            "id": task.id,
            "name": task.title,
            "description": task.description,
            "goal": [task.goal_id] if task.goal_id else [],
            "due_date": task.deadline,
            "priority": task.priority,
            "status": task.status,
            "order": getattr(task, "order", 0),
        }

    def _get_id(self, page):
        return page.get("id", "")

    def _get_props(self, page):
        return page.get("properties", {}) or {}

    # ============================================================
    # NOTION → LOCAL PARSERS
    # ============================================================
    def _get_text(self, props, field):
        try:
            return props[field]["title"][0]["plain_text"]
        except Exception:
            return ""

    def _get_rich(self, props, field):
        try:
            return props[field]["rich_text"][0]["plain_text"]
        except Exception:
            return ""

    def _get_select(self, props, field):
        try:
            return props[field]["select"]["name"]
        except Exception:
            return None

    def _get_number(self, props, field):
        try:
            return props[field]["number"]
        except Exception:
            return 0

    def _get_date(self, props, field):
        try:
            return props[field]["date"]["start"]
        except Exception:
            return None

    def _get_rels(self, props, field):
        try:
            return [r["id"] for r in props[field]["relation"]]
        except Exception:
            return []

    # ============================================================
    # MAPPING — GOALS
    # ============================================================
    def map_notion_goal_to_local(self, page) -> Dict[str, Any]:
        props = self._get_props(page)

        return {
            "id": self._get_id(page),
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
    def map_notion_task_to_local(self, page) -> Dict[str, Any]:
        props = self._get_props(page)

        return {
            "id": self._get_id(page),
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