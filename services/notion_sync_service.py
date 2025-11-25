import asyncio


class NotionSyncService:
    def __init__(self, notion_service, goals_service, tasks_service, goals_db_id, tasks_db_id):
        self.notion = notion_service
        self.goals = goals_service
        self.tasks = tasks_service
        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id

        # Debounce delay
        self._delay = 0.25

        # State flags to prevent infinite tasks
        self._goals_running = False
        self._tasks_running = False

    # ============================================================
    # GOALS DEBOUNCE
    # ============================================================
    async def debounce_goals_sync(self):
        if self._goals_running:
            return  # skip if already running

        self._goals_running = True
        try:
            await asyncio.sleep(self._delay)
            await self.sync_goals_up()
        finally:
            self._goals_running = False

    # ============================================================
    # TASKS DEBOUNCE
    # ============================================================
    async def debounce_tasks_sync(self):
        if self._tasks_running:
            return

        self._tasks_running = True
        try:
            await asyncio.sleep(self._delay)
            await self.sync_tasks_up()
        finally:
            self._tasks_running = False

    # ============================================================
    # SYNC GOALS → NOTION
    # ============================================================
    async def sync_goals_up(self):
        all_goals = self.goals.get_all()

        for g in all_goals:
            props = self.goals.to_dict(g)

            # If local goal has no Notion ID → create page
            if not g.notion_id:
                created = await self.notion.create_page(self.goals_db_id, props)
                if created.get("ok"):
                    new_id = created["data"]["id"]
                    old_id = g.id
                    g.notion_id = new_id
                    self.goals._replace_id(old_id, new_id)
            else:
                # Update page in Notion
                await self.notion.update_page(g.notion_id, props)

    # ============================================================
    # SYNC TASKS → NOTION
    # ============================================================
    async def sync_tasks_up(self):
        all_tasks = self.tasks.get_all()

        for t in all_tasks:
            props = self.tasks._to_dict(t)

            # If local task has no Notion ID → create
            if not t.notion_id:
                created = await self.notion.create_page(self.tasks_db_id, props)
                if created.get("ok"):
                    new_id = created["data"]["id"]
                    old_id = t.id
                    t.notion_id = new_id
                    self.tasks._replace_id(old_id, new_id)
            else:
                # Update page in Notion
                await self.notion.update_page(t.notion_id, props)