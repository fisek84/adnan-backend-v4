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

        # Use asyncio.create_task on current loop
        self._goals_task = asyncio.create_task(self._debounce(self.sync_goals_up))

    # ============================================================
    # SAFE DEBOUNCE for TASKS
    # ============================================================
    async def debounce_tasks_sync(self):
        if self._tasks_task and not self._tasks_task.done():
            self._tasks_task.cancel()

        self._tasks_task = asyncio.create_task(self._debounce(self.sync_tasks_up))

    # ============================================================
    # DEBOUNCE CORE
    # ============================================================
    async def _debounce(self, fn):
        try:
            await asyncio.sleep(self._delay)
            await fn()
        except asyncio.CancelledError:
            # Debounced, ignore
            pass
        except Exception:
            # Swallow errors to avoid killing loop
            pass

    # ============================================================
    # MAP LOCAL → NOTION STRUCTURES
    # ============================================================
    def map_local_goal_to_notion(self, g: dict):
        """
        Ovdje pretpostavljamo da GoalsService.to_dict(g) vraća:
        {
            "id", "notion_id", "title", "description",
            "deadline", "priority", "status",
            "progress", "parent_id", "children": [...]
        }
        """
        return {
            "Name": {"title": [{"text": {"content": g["title"] or ""}}]},
            "Description": {"rich_text": [{"text": {"content": g.get("description") or ""}}]},
            "Deadline": (
                {"date": {"start": g["deadline"]}}
                if g.get("deadline")
                else {"date": None}
            ),
            "Priority": (
                {"select": {"name": g["priority"]}}
                if g.get("priority")
                else {"select": None}
            ),
            "Status": {"select": {"name": g["status"]}},
            "Progress": {"number": g["progress"]},
            "Parent Goal": (
                {"relation": [{"id": g["parent_id"]}]}
                if g.get("parent_id")
                else {"relation": []}
            ),
            "Children": {
                "relation": [{"id": cid} for cid in g.get("children", [])]
            },
        }

    def map_local_task_to_notion(self, t: dict):
        """
        Ovdje pretpostavljamo da TasksService._to_dict(t) vraća:
        {
            "id", "notion_id", "title", "description",
            "goal_id", "deadline", "priority",
            "status", "order", ...
        }
        Property imena su usklađena sa Notion Tasks DB:
        - Title        → title
        - Description  → rich_text
        - Deadline     → date
        - Priority     → select
        - Status       → select
        - Goal         → relation
        - Order        → number
        - Task ID      → rich_text
        """
        return {
            "Title": {
                "title": [{"text": {"content": t["title"] or ""}}]
            },
            "Description": {
                "rich_text": [{"text": {"content": t.get("description") or ""}}]
            },
            "Deadline": (
                {"date": {"start": t["deadline"]}}
                if t.get("deadline")
                else {"date": None}
            ),
            "Priority": (
                {"select": {"name": t["priority"]}}
                if t.get("priority")
                else {"select": None}
            ),
            "Status": {"select": {"name": t["status"]}},
            "Goal": (
                {"relation": [{"id": t["goal_id"]}]}
                if t.get("goal_id")
                else {"relation": []}
            ),
            "Order": {"number": t["order"]},
            "Task ID": {
                "rich_text": [{"text": {"content": t["id"]}}]
            },
        }

    # ============================================================
    # SYNC GOALS → NOTION
    # ============================================================
    async def sync_goals_up(self):
        """
        Goals sync:
        - self.goals.get_all() → lista lokalnih goal objekata
        - self.goals.to_dict(g) → dict za mapiranje na Notion
        - self.goals._replace_id(old, new) → update lokalnih ID-eva kad Notion kreira novi ID
        """
        for g in self.goals.get_all():
            g_dict = self.goals.to_dict(g)
            props = self.map_local_goal_to_notion(g_dict)

            # CREATE
            if not g.notion_id:
                payload = {
                    "parent": {"database_id": self.goals_db_id},
                    "properties": props,
                }
                created = await self.notion.create_page(payload)
                if created["ok"]:
                    new_id = created["data"]["id"]
                    old = g.id
                    g.notion_id = new_id
                    # update lokalnog storage-a
                    self.goals._replace_id(old, new_id)
                continue

            # UPDATE
            update_payload = {"properties": props}
            await self.notion.update_page(g.notion_id, update_payload)

    # ============================================================
    # SYNC TASKS → NOTION
    # ============================================================
    async def sync_tasks_up(self):
        """
        Tasks sync:
        - self.tasks.get_all() → lista lokalnih task objekata
        - self.tasks._to_dict(t) → dict za mapiranje
        - self.tasks._replace_id(old, new) → update lokalnih ID-eva
        """
        for t in self.tasks.get_all():
            t_dict = self.tasks._to_dict(t)
            props = self.map_local_task_to_notion(t_dict)

            # CREATE
            if not t.notion_id:
                payload = {
                    "parent": {"database_id": self.tasks_db_id},
                    "properties": props,
                }
                created = await self.notion.create_page(payload)
                if created["ok"]:
                    new_id = created["data"]["id"]
                    old = t.id
                    t.notion_id = new_id
                    self.tasks._replace_id(old, new_id)
                continue

            # UPDATE
            update_payload = {"properties": props}
            await self.notion.update_page(t.notion_id, update_payload)
