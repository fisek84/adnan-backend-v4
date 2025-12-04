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
    # GENERIC DEBOUNCE
    # ------------------------------------------------------
    async def _debounce(self, fn):
        try:
            await asyncio.sleep(self._delay)
            await fn()
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------
    # PROJECT SYNC REQUEST
    # ------------------------------------------------------
    def add_project_for_sync(self):
        try:
            loop = asyncio.get_running_loop()

            if self._project_sync_task and not self._project_sync_task.done():
                self._project_sync_task.cancel()

            self._project_sync_task = loop.create_task(
                self._debounce(self.sync_projects_up)
            )

        except RuntimeError:
            asyncio.run(self._debounce(self.sync_projects_up))

    # ------------------------------------------------------
    # LOAD PROJECTS FROM NOTION
    # ------------------------------------------------------
    async def get_all_projects_from_notion(self):
        self.logger.info("📥 Loading projects from Notion...")
        return await self.notion.query_database(self.projects_db_id)

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

    async def load_projects_into_backend(self):
        remote = await self.get_all_projects_from_notion()
        if not remote["ok"]:
            return

        results = remote["data"]["results"]

        for page in results:
            mapped = self.map_project_page(page)
            if not mapped:
                continue

            if mapped["id"] in self.projects.projects:
                self.projects.projects[mapped["id"]].tasks = mapped["tasks"]
                continue

            self.projects.create_project(
                data=self.projects.to_create_model(mapped),
                forced_id=mapped["id"],
                notion_id=mapped["notion_id"]
            )

    # ------------------------------------------------------
    # MAP LOCAL PROJECT TO NOTION
    # ------------------------------------------------------
    def map_local_project_to_notion(self, p: dict):
        def wrap(x):
            return {"rich_text": [{"text": {"content": x or ""}}]}

        return {
            "Project Name": {"title": [{"text": {"content": p.get("title")}}]},
            "Description": wrap(p.get("description")),
            "Status": {"select": {"name": p.get("status")}},
            "Category": {"select": {"name": p.get("category")}} if p.get("category") else None,
            "Priority": {"select": {"name": p.get("priority")}} if p.get("priority") else None,
            "Start Date": {"date": {"start": p.get("start_date")}} if p.get("start_date") else None,
            "Target Deadline": {"date": {"start": p.get("deadline")}} if p.get("deadline") else None,
            "Project Type": {"select": {"name": p.get("project_type")}} if p.get("project_type") else None,
            "Summary": wrap(p.get("summary")),
            "Next Step": wrap(p.get("next_step")),
            "Primary Goal": {"relation": [{"id": p.get("primary_goal_id")}]} if p.get("primary_goal_id") else {"relation": []},
            "Parent Project": {"relation": [{"id": p.get("parent_id")}]} if p.get("parent_id") else {"relation": []},
            "Agent Exchange DB": {"relation": [{"id": a} for a in p.get("agents", [])]},
            "Tasks DB": {"relation": [{"id": t} for t in p.get("tasks", [])]},
            "Handled By": wrap(p.get("handled_by")),
        }

    # ------------------------------------------------------
    # PROJECT SYNC
    # ------------------------------------------------------
    async def sync_projects_up(self):
        for p in self.projects.get_all():
            data = self.projects.to_dict(p)
            props = self.map_local_project_to_notion(data)

            if not p.notion_id:
                created = await self.notion.create_page({
                    "parent": {"database_id": self.projects_db_id},
                    "properties": props
                })
                if created["ok"]:
                    self.projects._replace_id(p.id, created["data"]["id"])
                continue

            await self.notion.update_page(p.notion_id, {"properties": props})

    # ------------------------------------------------------
    # GOALS SYNC — DEBOUNCE
    # ------------------------------------------------------
    def debounce_goals_sync(self):
        try:
            loop = asyncio.get_running_loop()

            if self._goal_sync_task and not self._goal_sync_task.done():
                self._goal_sync_task.cancel()

            self._goal_sync_task = loop.create_task(
                self._debounce(self.sync_goals_up)
            )
        except RuntimeError:
            asyncio.run(self._debounce(self.sync_goals_up))

    # ------------------------------------------------------
    # GOALS SYNC — REAL
    # ------------------------------------------------------
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
                if created["ok"]:
                    goal.notion_id = created["data"]["id"]
                continue

            await self.notion.update_page(goal.notion_id, {"properties": props})

    # ------------------------------------------------------
    # TASKS SYNC — DEBOUNCE
    # ------------------------------------------------------
    def debounce_tasks_sync(self):
        try:
            loop = asyncio.get_running_loop()

            if self._task_sync_task and not self._task_sync_task.done():
                self._task_sync_task.cancel()

            self._task_sync_task = loop.create_task(
                self._debounce(self.sync_tasks_up)
            )

        except RuntimeError:
            asyncio.run(self._debounce(self.sync_tasks_up))

    # ------------------------------------------------------
    # TASKS SYNC — REAL
    # ------------------------------------------------------
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

            if task.goal_id:
                props["Goal"] = {"relation": [{"id": task.goal_id}]}
            else:
                props["Goal"] = {"relation": []}

            if not task.notion_id:
                created = await self.notion.create_page({
                    "parent": {"database_id": self.tasks_db_id},
                    "properties": props
                })
                if created["ok"]:
                    task.notion_id = created["data"]["id"]
                continue

            await self.notion.update_page(task.notion_id, {"properties": props})
