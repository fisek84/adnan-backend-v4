import asyncio
from typing import Any, Dict, List, Optional


class NotionSyncService:
    """
    Evolia Notion Sync Engine v4 (Async, Stable, Error-Aware)

    - Fully async
    - Safe debounce
    - Detects Notion soft errors (object: error)
    - Auto-replaces temporary UUID with real Notion page ID
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

    # ============================================================
    # DEBOUNCE
    # ============================================================
    async def debounce_goals_sync(self):
        self._cancel(self._goals_db_task)
        self._goals_db_task = asyncio.create_task(self._debounce(self.sync_goals_up))

    async def debounce_tasks_sync(self):
        self._cancel(self._tasks_db_task)
        self._tasks_db_task = asyncio.create_task(self._debounce(self.sync_tasks_up))

    async def _debounce(self, fn):
        try:
            await asyncio.sleep(self._delay)
            await fn()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"[NotionSync] Debounce error:", e)

    @staticmethod
    def _cancel(task: Optional[asyncio.Task]):
        if task and not task.done():
            task.cancel()

    # ============================================================
    # SYNC UP (LOCAL → NOTION)
    # ============================================================
    async def sync_goals_up(self):
        for goal in self.goals.get_all():
            goal_dict = self.goals.to_dict(goal)
            props = self.map_local_goal_to_notion(goal_dict)

            # ------------------------------
            # TRY UPDATE
            # ------------------------------
            update = await self.notion.update_page(goal.id, props)

            if update.get("ok"):
                continue

            # if Notion returns soft error (object: error)
            if update.get("error"):
                print("[NotionSync] Goal update failed → will create instead:", update["error"])

            # ------------------------------
            # TRY CREATE
            # ------------------------------
            create = await self.notion.create_page(self.goals_db_id, props)

            if create.get("ok"):
                goal.id = create["data"]["id"]  # replace temp ID
            else:
                print("[NotionSync] Goal create failed:", create.get("error"))

    async def sync_tasks_up(self):
        for task in self.tasks.get_all():
            task_dict = self._task_to_dict(task)
            props = self.map_local_task_to_notion(task_dict)

            update = await self.notion.update_page(task.id, props)

            if update.get("ok"):
                continue

            if update.get("error"):
                print("[NotionSync] Task update failed → will create:", update["error"])

            create = await self.notion.create_page(self.tasks_db_id, props)

            if create.get("ok"):
                task.id = create["data"]["id"]
            else:
                print("[NotionSync] Task create failed:", create.get("error"))

    # ============================================================
    # SYNC DOWN (NOTION → LOCAL)
    # ============================================================
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

    # ============================================================
    # FETCH ALL FROM DB
    # ============================================================
    async def _fetch_all(self, db_id: str):
        results = []
        cursor = None

        while True:
            payload = {"start_cursor": cursor} if cursor else {}

            resp = await self.notion.query_database(db_id, payload)

            if not resp.get("ok"):
                print("[NotionSync] fetch_all error:", resp.get("error"))
                break

            data = resp["data"]
            results.extend(data.get("results", []))

            if not data.get("has_more"):
                break

            cursor = data.get("next_cursor")

        return results

    # ============================================================
    # HELPERS
    # ============================================================
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
            return [item["id"] for item in props[key]["relation"]]
        except:
            return []

    def _task_to_dict(self, task):
        return {
            "id": task.id,
            "name": task.title,
            "description": task.description,
            "due_date": task.deadline,
            "goal": [task.goal_id] if task.goal_id else [],
            "priority": task.priority,
            "status": task.status,
            "order": task.order,
        }

    # ============================================================
    # MAPPING — GOALS
    # ============================================================
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
            "type": self._select(props, "Type"),
        }

    def map_local_goal_to_notion(self, g):

        def text(v): return [{"type": "text", "text": {"content": v or ""}}]
        def sel(v): return {"name": v} if v else None
        def rel(ids): return [{"id": x} for x in ids] if ids else []

        props = {
            "Name": {"title": text(g.get("name"))},
            "Status": {"select": sel(g.get("status"))},
            "Auto Status": {"select": sel(g.get("auto_status"))},
            "Deadline": (
                {"date": {"start": g.get("deadline")}}
                if g.get("deadline") else None
            ),
            "Progress": {"number": g.get("progress", 0)},
            "Parent Goal": {"relation": rel(g.get("parent_goal", []))},
            "Child Goals": {"relation": rel(g.get("child_goals", []))},
            "Description": {"rich_text": text(g.get("description"))},
            "Type": {"select": sel(g.get("type"))},
        }

        return {k: v for k, v in props.items() if v is not None}

    # ============================================================
    # MAPPING — TASKS
    # ============================================================
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

    def map_local_task_to_notion(self, t):

        def text(v): return [{"type": "text", "text": {"content": v or ""}}]
        def sel(v): return {"name": v} if v else None
        def rel(ids): return [{"id": x} for x in ids] if ids else []

        props = {
            "Name": {"title": text(t.get("name"))},
            "Status": {"select": sel(t.get("status"))},
            "Priority": {"select": sel(t.get("priority"))},
            "Due Date": (
                {"date": {"start": t.get("due_date")}}
                if t.get("due_date") else None
            ),
            "Goal": {"relation": rel(t.get("goal", []))},
            "Order": {"number": t.get("order", 0)},
            "Description": {"rich_text": text(t.get("description"))},
        }

        return {k: v for k, v in props.items() if v is not None}