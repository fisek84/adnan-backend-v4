import asyncio
import aiohttp


class NotionSyncService:
    def __init__(self, notion_service, goals_service, tasks_service, goals_db_id, tasks_db_id):
        self.notion = notion_service
        self.goals = goals_service
        self.tasks = tasks_service

        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id

        # Delay for debounce
        self._delay = 0.25

        # Internal async tasks
        self._goals_task: asyncio.Task | None = None
        self._tasks_task: asyncio.Task | None = None

        # Loop will be injected on FastAPI startup
        self.loop = None

    # ============================================================
    # INITIALIZE LOOP FROM FASTAPI
    # ============================================================
    async def start(self):
        # Take FastAPI's main running event loop
        self.loop = asyncio.get_running_loop()

    # ============================================================
    # SAFE DEBOUNCE for GOALS
    # ============================================================
    async def debounce_goals_sync(self):
        if self._goals_task and not self._goals_task.done():
            self._goals_task.cancel()

        # Important: Use asyncio.create_task, not a custom loop
        self._goals_task = asyncio.create_task(self._debounce(self.sync_goals_up))

    # ============================================================
    # SAFE DEBOUNCE for TASKS
    # ============================================================
    async def debounce_tasks_sync(self):
        if self._tasks_task and not self._tasks_task.done():
            self._tasks_task.cancel()

        # Important: Use asyncio.create_task
        self._tasks_task = asyncio.create_task(self._debounce(self.sync_tasks_up))

    # ============================================================
    # DEBOUNCE CORE
    # ============================================================
    async def _debounce(self, fn):
        try:
            await asyncio.sleep(self._delay)
            await fn()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    # ============================================================
    # MAP LOCAL → NOTION STRUCTURES
    # ============================================================
    def map_local_goal_to_notion(self, g: dict):
        return {
            "Name": {"title": [{"text": {"content": g["title"] or ""}}]},
            "Description": {"rich_text": [{"text": {"content": g.get("description") or ""}}]},
            "Deadline": {"date": {"start": g["deadline"]}} if g.get("deadline") else {"date": None},
            "Priority": {"select": {"name": g["priority"]}} if g.get("priority") else {"select": None},
            "Status": {"select": {"name": g["status"]}},
            "Progress": {"number": g["progress"]},
            "Parent Goal": {"relation": [{"id": g["parent_id"]}]} if g.get("parent_id") else {"relation": []},
            "Children": {"relation": [{"id": cid} for cid in g["children"]]},
        }

    def map_local_task_to_notion(self, t: dict):
        return {
            "Name": {"title": [{"text": {"content": t["name"]}}]},
            "Description": {"rich_text": [{"text": {"content": t.get("description") or ""}}]},
            "Deadline": {"date": {"start": t["due_date"]}} if t.get("due_date") else {"date": None},
            "Priority": {"select": {"name": t["priority"]}} if t.get("priority") else {"select": None},
            "Status": {"select": {"name": t["status"]}},
            "Goal": {"relation": [{"id": t["goal"][0]}]} if t["goal"] else {"relation": []},
        }

    # ============================================================
    # SYNC GOALS → NOTION
    # ============================================================
    async def sync_goals_up(self):
        for g in self.goals.get_all():
            props = self.map_local_goal_to_notion(self.goals.to_dict(g))

            # CREATE
            if not g.notion_id:
                created = await self.notion.create_page(self.goals_db_id, props)
                if created["ok"]:
                    new_id = created["data"]["id"]
                    old = g.id
                    g.notion_id = new_id
                    self.goals._replace_id(old, new_id)
                continue

            # UPDATE
            await self.notion.update_page(g.notion_id, props)

    # ============================================================
    # SYNC TASKS → NOTION
    # ============================================================
    async def sync_tasks_up(self):
        for t in self.tasks.get_all():
            props = self.map_local_task_to_notion(self.tasks._to_dict(t))

            # CREATE
            if not t.notion_id:
                created = await self.notion.create_page(self.tasks_db_id, props)
                if created["ok"]:
                    new_id = created["data"]["id"]
                    old = t.id
                    t.notion_id = new_id
                    self.tasks._replace_id(old, new_id)
                continue

            # UPDATE
            await self.notion.update_page(t.notion_id, props)
