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

        # Debounce task holders
        self._project_sync_task = None
        self._goal_sync_task = None
        self._task_sync_task = None

        # Logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

    # ------------------------------------------------------
    # INTERNAL DEBOUNCE WRAPPER
    # ------------------------------------------------------
    async def _debounce(self, fn):
        try:
            await asyncio.sleep(self._delay)
            await fn()
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------
    # PROJECT SYNC DEBOUNCE
    # ------------------------------------------------------
    async def debounce_projects_sync(self):
        loop = asyncio.get_running_loop()

        if self._project_sync_task and not self._project_sync_task.done():
            self._project_sync_task.cancel()

        self._project_sync_task = loop.create_task(
            self._debounce(self.sync_projects_up)
        )

    # ------------------------------------------------------
    # GOALS SYNC DEBOUNCE
    # ------------------------------------------------------
    async def debounce_goals_sync(self):
        loop = asyncio.get_running_loop()

        if self._goal_sync_task and not self._goal_sync_task.done():
            self._goal_sync_task.cancel()

        self._goal_sync_task = loop.create_task(
            self._debounce(self.sync_goals_up)
        )

    # ------------------------------------------------------
    # TASKS SYNC DEBOUNCE
    # ------------------------------------------------------
    async def debounce_tasks_sync(self):
        loop = asyncio.get_running_loop()

        if self._task_sync_task and not self._task_sync_task.done():
            self._task_sync_task.cancel()

        self._task_sync_task = loop.create_task(
            self._debounce(self.sync_tasks_up)
        )

    # ------------------------------------------------------
    # LOAD PROJECTS FROM NOTION → BACKEND (REQUIRED BY main.py)
    # ------------------------------------------------------
    async def load_projects_into_backend(self):
        self.logger.info("📥 Loading projects from Notion into backend...")

        response = await self.notion.query_database(self.projects_db_id)

        if not response.get("ok"):
            self.logger.error("Failed to load projects from Notion")
            return

        pages = response["data"]["results"]

        for page in pages:
            mapped = self.map_project_page(page)
            if not mapped:
                continue

            project_id = mapped["id"]

            # If backend already has this project → update tasks
            if project_id in self.projects.projects:
                self.projects.projects[project_id].tasks = mapped["tasks"]
                continue

            # Otherwise create new project in backend
            self.projects.create_project(
                data=self.projects.to_create_model(mapped),
                forced_id=project_id,
                notion_id=mapped["notion_id"]
            )

        self.logger.info(f"📁 Loaded {len(pages)} projects from Notion → backend OK")

    # ------------------------------------------------------
    # MAP NOTION PROJECT PAGE → PYTHON STRUCTURE
    # ------------------------------------------------------
    def map_project_page(self, page):
        props = page.get("properties", {})

        def safe(name, kind):
            prop = props.get(name)
            if not prop:
                return None

            try:
                if kind == "title":
                    return prop["title"][0]["plain_text"] if prop["title"] else ""
                if kind == "text":
                    return prop["rich_text"][0]["plain_text"] if prop["rich_text"] else ""
                if kind == "select":
                    return prop["select"]["name"] if prop["select"] else None
                if kind == "date":
                    return prop["date"]["start"] if prop["date"] else None
                if kind == "relation":
                    rel = prop.get("relation") or []
                    return [r["id"].replace("-", "") for r in rel]
            except:
                return None

            return None

        title = safe("Project Name", "title")
        if not title:
            return None

        return {
            "id": page["id"].replace("-", ""),
            "notion_id": page["id"],
            "title": title,
            "description": safe("Description", "text"),
            "status": safe("Status", "select") or "Active",
            "category": safe("Category", "select"),
            "priority": safe("Priority", "select"),
            "start_date": safe("Start Date", "date"),
            "deadline": safe("Target Deadline", "date"),
            "project_type": safe("Project Type", "select"),
            "summary": safe("Summary", "text"),
            "next_step": safe("Next Step", "text"),
            "primary_goal_id": (
                safe("Primary Goal", "relation")[0]
                if safe("Primary Goal", "relation") else None
            ),
            "parent_id": (
                safe("Parent Project", "relation")[0]
                if safe("Parent Project", "relation") else None
            ),
            "agents": safe("Agent Exchange DB", "relation") or [],
            "tasks": safe("Tasks DB", "relation") or [],
            "handled_by": safe("Handled By", "text"),
            "progress": 0,
        }
