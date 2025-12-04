# services/notion_sync_service.py
import asyncio
import logging


class NotionSyncService:
    def __init__(
        self,
        notion_service,
        goals_service,
        tasks_service,
        projects_service,
        goals_db_id,
        tasks_db_id,
        projects_db_id
    ):
        self.notion = notion_service
        self.goals = goals_service
        self.tasks = tasks_service
        self.projects = projects_service

        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id
        self.projects_db_id = projects_db_id

        self._delay = 0.25

        self._project_sync_task = None
        self._goal_sync_task = None
        self._task_sync_task = None

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

    # DEBOUNCE WRAPPER
    async def _debounce(self, fn):
        try:
            await asyncio.sleep(self._delay)
            await fn()
        except asyncio.CancelledError:
            pass

    # PROJECT SYNC DEBOUNCE
    async def debounce_projects_sync(self):
        loop = asyncio.get_running_loop()
        if self._project_sync_task and not self._project_sync_task.done():
            self._project_sync_task.cancel()

        self._project_sync_task = loop.create_task(
            self._debounce(self.sync_projects_up)
        )

    # GOALS SYNC DEBOUNCE
    async def debounce_goals_sync(self):
        loop = asyncio.get_running_loop()
        if self._goal_sync_task and not self._goal_sync_task.done():
            self._goal_sync_task.cancel()

        self._goal_sync_task = loop.create_task(
            self._debounce(self.sync_goals_up)
        )

    # TASKS SYNC DEBOUNCE
    async def debounce_tasks_sync(self):
        loop = asyncio.get_running_loop()
        if self._task_sync_task and not self._task_sync_task.done():
            self._task_sync_task.cancel()

        self._task_sync_task = loop.create_task(
            self._debounce(self.sync_tasks_up)
        )

    # ------------------------
    # SYNC PROJECTS
    # ------------------------
    async def sync_projects_up(self):
        for p in self.projects.get_all():
            props = self.map_local_project_to_notion(self.projects.to_dict(p))

            if not p.notion_id:
                created = await self.notion.create_page({
                    "parent": {"database_id": self.projects_db_id},
                    "properties": props
                })
                if created.get("ok"):
                    self.projects._replace_id(p.id, created["data"]["id"])
                continue

            await self.notion.update_page(p.notion_id, {"properties": props})

    # ------------------------
    # SYNC GOALS
    # ------------------------
    async def sync_goals_up(self):
        for goal in self.goals.get_all():
            props = {
                "Name": {"title": [{"text": {"content": goal.title}}]},
                "Status": {"select": {"name": goal.status}},
                "Progress": {"number": goal.progress},
            }
            if goal.priority:
                props["Priority"] = {"select": {"name": goal.priority}}
            if goal.deadline:
                props["Deadline"] = {"date": {"start": goal.deadline}}

            if not goal.notion_id:
                created = await self.notion.create_page({
                    "parent": {"database_id": self.goals_db_id},
                    "properties": props
                })
                if created.get("ok"):
                    goal.notion_id = created["data"]["id"]
                continue

            await self.notion.update_page(goal.notion_id, {"properties": props})

    # ------------------------
    # SYNC TASKS
    # ------------------------
    async def sync_tasks_up(self):
        for task in self.tasks.get_all_tasks():
            props = {
                "Name": {"title": [{"text": {"content": task.title}}]},
                "Status": {"select": {"name": task.status}},
                "Order": {"number": task.order},
            }
            if task.priority:
                props["Priority"] = {"select": {"name": task.priority}}
            if task.deadline:
                props["Due Date"] = {"date": {"start": task.deadline}}

            # relation
            if task.goal_id:
                props["Goal"] = {"relation": [{"id": task.goal_id}]}
            else:
                props["Goal"] = {"relation": []}

            if not task.notion_id:
                created = await self.notion.create_page({
                    "parent": {"database_id": self.tasks_db_id},
                    "properties": props
                })
                if created.get("ok"):
                    task.notion_id = created["data"]["id"]
                continue

            await self.notion.update_page(task.notion_id, {"properties": props})


    # (ako koristiš map_local_project_to_notion, ostavi i taj helper)
    def map_local_project_to_notion(self, p):
        def wrap(x):
            return {"rich_text": [{"text": {"content": x or ''}}]}

        return {
            "Project Name": {"title": [{"text": {"content": p.get("title")}}]},
            "Description": wrap(p.get("description")),
            "Status": {"select": {"name": p.get("status")}},
        }
