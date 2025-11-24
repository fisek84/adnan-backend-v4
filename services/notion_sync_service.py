import asyncio
from typing import Any, Dict, List, Optional


class NotionSyncService:
    """
    Evolia Notion Sync Engine v4 (Async, Stable)

    - Fully async
    - Push + Pull
    - Debounce-safe
    - Works with new async NotionService
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

        self._goals_db_task: Optional[asyncio.Task] = None
        self._tasks_db_task: Optional[asyncio.Task] = None
        self._delay = 0.25

    # =============================================================
    # DEBOUNCE
    # =============================================================
    async def debounce_goals_sync(self):
        self._cancel(self._goals_db_task)
        self._goals_db_task = asyncio.create_task(
            self._debounce(self.sync_goals_up)
        )

    async def debounce_tasks_sync(self):
        self._cancel(self._tasks_db_task)
        self._tasks_db_task = asyncio.create_task(
            self._debounce(self.sync_tasks_up)
        )

    async def _debounce(self, fn):
        try:
            await asyncio.sleep(self._delay)
            await fn()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[NotionSync] Debounce error: {e}")

    @staticmethod
    def _cancel(task):
        if task and not task.done():
            task.cancel()

    # =============================================================
    # SYNC UP (LOCAL → NOTION)
    # =============================================================
    async def sync_goals_up(self):
        goals = self.goals.get_all()

        for goal in goals:
            as_dict = self.goals.to_dict(goal)
            properties = self.map_local_goal_to_notion(as_dict)

            # --------------------------------------------
            # UPDATE existing (if ID matches Notion page)
            # --------------------------------------------
            update_resp = await self.notion.update_page(goal.id, properties)

            if update_resp.get("ok"):
                continue  # updated successfully

            # --------------------------------------------
            # CREATE new (if not found or bad ID)
            # --------------------------------------------
            create_resp = await self.notion.create_page(
                self.goals_db_id,
                properties
            )

            if create_resp.get("ok"):
                notion_id = create_resp["data"]["id"]
                goal.id = notion_id  # Replace internal with Notion ID

    async def sync_tasks_up(self):
        tasks = self.tasks.get_all()

        for task in tasks:
            task_dict = self._task_to_dict(task)
            properties = self.map_local_task_to_notion(task_dict)

            update_resp = await self.notion.update_page(task.id, properties)

            if update_resp.get("ok"):
                continue

            create_resp = await self.notion.create_page(
                self.tasks_db_id,
                properties
            )

            if create_resp.get("ok"):
                notion_id = create_resp["data"]["id"]
                task.id = notion_id

    # =============================================================
    # SYNC DOWN (NOTION → LOCAL)
    # =============================================================
    async def sync_goals_down(self):
        pages = await self._fetch_all(self.goals_db_id)

        for page in pages:
            mapped = self.map_notion_goal_to_local(page)
            self.goals.sync_from_notion(mapped)

    async def sync_tasks_down(self):
        pages = await self._fetch_all(self.tasks_db_id)

        for page in pages:
            mapped = self.map_notion_task_to_local(page)
            self.tasks.sync_from_notion(mapped)

    # =============================================================
    # QUERY HELPERS
    # =============================================================
    async def _fetch_all(self, db_id: str):
        results = []
        cursor = None

        while True:
            payload = {}
            if cursor:
                payload["start_cursor"] = cursor

            resp = await self.notion.query_database(db_id, payload)

            if not resp.get("ok"):
                break

            data = resp["data"]
            results.extend(data.get("results", []))

            if not data.get("has_more"):
                break

            cursor = data.get("next_cursor")

        return results

    # =============================================================
    # MAPPING UTIL
    # =============================================================
    def _props(self, page):
        return page.get("properties", {})

    def _id(self, page):
        return page.get("id", "")

    def _text(self, props, key):
        try:
            return props[key]["title"][0]["plain_text"]
        except:
            return ""

    def _rich(self, props, key):
        try:
            return props[key]["rich_text"][0]["plain_text"]
        except:
            return ""

    def _select(self, props, key):
        try:
            return props[key]["select"]["name"]
        except:
            return None

    def _number(self, props, key):
        try:
            return props[key]["number"]
        except:
            return 0

    def _date(self, props, key):
        try:
            return props[key]["date"]["start"]
        except:
            return None

    def _rels(self, props, key):
        try:
            return [x["id"] for x in props[key]["relation"]]
        except:
            return []

    # =============================================================
    # NOTION → LOCAL (GOALS)
    # =============================================================
    def map_notion_goal_to_local(self, page):
        props = self._props(page)

        return {
            "id": self._id(page),
            "name": self._text(props, "Name"),
            "status": self._select(props, "Status"),
            "auto_status": self._select(props, "Auto Status"),
            "deadline": self._date(props, "Deadline"),
            "progress": self._number(props, "Progress"),
            "parent_goal": self._rels(props, "Parent Goal"),
            "child_goals": self._rels(props, "Child Goals"),
            "description": self._rich(props, "Description"),
            "type": self._select(props, "Type")
        }

    # =============================================================
    # LOCAL → NOTION (GOALS)
    # =============================================================
    def map_local_goal_to_notion(self, goal: Dict[str, Any]):

        def text(v): return [{"type": "text", "text": {"content": v or ""}}]
        def sel(v): return {"name": v} if v else None
        def rel(ids): return [{"id": x} for x in ids] if ids else []

        props = {
            "Name": {"title": text(goal.get("name", ""))},
            "Status": {"select": sel(goal.get("status"))},
            "Auto Status": {"select": sel(goal.get("auto_status"))},
            "Deadline": (
                {"date": {"start": goal.get("deadline")}}
                if goal.get("deadline") else None
            ),
            "Progress": {"number": goal.get("progress", 0)},
            "Parent Goal": {"relation": rel(goal.get("parent_goal", []))},
            "Child Goals": {"relation": rel(goal.get("child_goals", []))},
            "Description": {"rich_text": text(goal.get("description", ""))},
            "Type": {"select": sel(goal.get("type"))},
        }

        return {k: v for k, v in props.items() if v is not None}

    # =============================================================
    # NOTION → LOCAL (TASKS)
    # =============================================================
    def map_notion_task_to_local(self, page):
        props = self._props(page)

        return {
            "id": self._id(page),
            "name": self._text(props, "Name"),
            "status": self._select(props, "Status"),
            "priority": self._select(props, "Priority"),
            "due_date": self._date(props, "Due Date"),
            "goal": self._rels(props, "Goal"),
            "order": self._number(props, "Order"),
            "description": self._rich(props, "Description"),
        }

    # =============================================================
    # LOCAL → NOTION (TASKS)
    # =============================================================
    def map_local_task_to_notion(self, task: Dict[str, Any]):

        def text(v): return [{"type": "text", "text": {"content": v or ""}}]
        def sel(v): return {"name": v} if v else None
        def rel(ids): return [{"id": x} for x in ids] if ids else []

        props = {
            "Name": {"title": text(task.get("name", ""))},
            "Status": {"select": sel(task.get("status"))},
            "Priority": {"select": sel(task.get("priority"))},
            "Due Date": (
                {"date": {"start": task.get("due_date")}}
                if task.get("due_date") else None
            ),
            "Goal": {"relation": rel(task.get("goal", []))},
            "Order": {"number": task.get("order", 0)},
            "Description": {"rich_text": text(task.get("description", ""))},
        }

        return {k: v for k, v in props.items() if v is not None}