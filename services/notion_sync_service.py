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

        self._delay = 0.3

        # Debounce task handlers
        self._sync_projects_task = None
        self._goals_debounce_task = None
        self._tasks_debounce_task = None  # required by TasksService

        # Logger
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

    # ------------------------------------------------------
    # DEBOUNCE WRAPPER
    # ------------------------------------------------------
    async def _debounce(self, fn):
        try:
            await asyncio.sleep(self._delay)
            await fn()
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------
    # ADD PROJECT FOR SYNC
    # ------------------------------------------------------
    def add_project_for_sync(self, project, delete=False):
        self.logger.info(f"🔄 [SYNC] Queued project: {project.title}")

        async def schedule_sync():
            await self._debounce(self.sync_projects_up)

        try:
            loop = asyncio.get_running_loop()

            if self._sync_projects_task and not self._sync_projects_task.done():
                self._sync_projects_task.cancel()

            self._sync_projects_task = loop.create_task(schedule_sync())

        except RuntimeError:
            self.logger.warning("⚠️ No running event loop — running sync directly.")
            asyncio.run(self._debounce(self.sync_projects_up))

    # ------------------------------------------------------
    # LOAD PROJECTS FROM NOTION
    # ------------------------------------------------------
    async def get_all_projects_from_notion(self):
        self.logger.info("📥 Loading projects from Notion...")
        return await self.notion.query_database(self.projects_db_id)

    def map_project_page(self, page):
        self.logger.info(f"Mapping project page: {page['id']}")
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
        if not title or title.strip() == "":
            raise ValueError(f"Project in Notion has no title: {page['id']}")

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
        self.logger.info("📥 Loading projects from Notion into backend...")
        remote = await self.get_all_projects_from_notion()
        if not remote.get("ok"):
            self.logger.warning("⚠️ Failed loading Notion projects")
            return

        results = remote["data"]["results"]

        for page in results:
            mapped = self.map_project_page(page)

            if mapped["id"] in self.projects.projects:
                self.projects.projects[mapped["id"]].tasks = mapped["tasks"]
                continue

            self.projects.create_project(
                data=self.projects.to_create_model(mapped),
                forced_id=mapped["id"],
                notion_id=mapped["notion_id"]
            )

        self.logger.info(f"📁 Loaded {len(results)} projects from Notion")

    # ------------------------------------------------------
    # PROJECT SYNC UP
    # ------------------------------------------------------
    def map_local_project_to_notion(self, p: dict):
        self.logger.info(f"Mapping local project to Notion: {p['title']}")

        def wrap(x):
            return {"rich_text": [{"text": {"content": x or ""}}]}

        return {
            "Project Name": {"title": [{"text": {"content": p.get("title") or ""}}]},
            "Description": wrap(p.get("description")),
            "Status": {"select": {"name": p.get("status")}} if p.get("status") else None,
            "Category": {"select": {"name": p.get("category")}} if p.get("category") else None,
            "Priority": {"select": {"name": p.get("priority")}} if p.get("priority") else None,
            "Start Date": {"date": {"start": p.get("start_date")}} if p.get("start_date") else {"date": None},
            "Target Deadline": {"date": {"start": p.get("deadline")}} if p.get("deadline") else {"date": None},
            "Project Type": {"select": {"name": p.get("project_type")}} if p.get("project_type") else None,
            "Summary": wrap(p.get("summary")),
            "Next Step": wrap(p.get("next_step")),
            "Primary Goal": {"relation": [{"id": p.get("primary_goal_id")}]} if p.get("primary_goal_id") else {"relation": []},
            "Parent Project": {"relation": [{"id": p.get("parent_id")}]} if p.get("parent_id") else {"relation": []},
            "Agent Exchange DB": {"relation": [{"id": a} for a in p.get("agents", [])]},
            "Tasks DB": {"relation": [{"id": t} for t in p.get("tasks", [])]},
            "Handled By": wrap(p.get("handled_by")),
        }

    async def sync_projects_up(self):
        self.logger.info("🚀 SYNC: Uploading projects to Notion...")

        for p in self.projects.get_all():
            p_dict = self.projects.to_dict(p)
            props = self.map_local_project_to_notion(p_dict)

            if not p.notion_id:
                self.logger.info(f"📌 Creating new Notion page for project: {p.title}")

                created = await self.notion.create_page({
                    "parent": {"database_id": self.projects_db_id},
                    "properties": props
                })

                if created.get("ok"):
                    new_id = created["data"]["id"]
                    self.projects._replace_id(p.id, new_id)
                continue

            self.logger.info(f"♻️ Updating page for project: {p.title}")
            await self.notion.update_page(p.notion_id, {"properties": props})

        self.logger.info("✅ PROJECT SYNC COMPLETE")

    # ============================================================
    #  GOALS SYNC — DEBOUNCE
    # ============================================================
    def debounce_goals_sync(self):
        self.logger.info("⏳ Debounce: goals sync triggered")

        async def schedule():
            await self._debounce(self.sync_goals_up)

        try:
            loop = asyncio.get_running_loop()

            if self._goals_debounce_task and not self._goals_debounce_task.done():
                self._goals_debounce_task.cancel()

            self._goals_debounce_task = loop.create_task(schedule())

        except RuntimeError:
            asyncio.run(self._debounce(self.sync_goals_up))

    # ============================================================
    #  GOALS SYNC — REAL SYNC UP
    # ============================================================
    async def sync_goals_up(self):
        self.logger.info("🚀 SYNC: Uploading goals to Notion...")

        try:
            for goal in self.goals.get_all():

                # CREATE NEW GOAL
                if not goal.notion_id:
                    self.logger.info(f"📌 Creating new Notion goal: {goal.title}")

                    payload = {
                        "parent": {"database_id": self.goals_db_id},
                        "properties": {
                            "Name": {"title": [{"text": {"content": goal.title}}]},
                            "Status": {"select": {"name": goal.status}},
                            "Priority": {"select": {"name": goal.priority}} if goal.priority else None,
                            "Deadline": {"date": {"start": goal.deadline}} if goal.deadline else {"date": None},
                        }
                    }

                    created = await self.notion.create_page(payload)

                    if created.get("ok"):
                        goal.notion_id = created["data"]["id"]
                        self.logger.info(f"🆕 Goal synced to Notion with ID: {goal.notion_id}")

                    continue

                # UPDATE EXISTING GOAL
                self.logger.info(f"♻️ Updating goal in Notion: {goal.title}")

                update_payload = {
                    "properties": {
                        "Name": {"title": [{"text": {"content": goal.title}}]},
                        "Status": {"select": {"name": goal.status}},
                        "Priority": {"select": {"name": goal.priority}} if goal.priority else None,
                        "Deadline": {"date": {"start": goal.deadline}} if goal.deadline else {"date": None},
                    }
                }

                await self.notion.update_page(goal.notion_id, update_payload)

            self.logger.info("✅ GOALS SYNC COMPLETE")

        except Exception as e:
            self.logger.error(f"❌ Goal sync error: {e}")

    # ============================================================
    #  TASKS SYNC — DEBOUNCE
    # ============================================================
    def debounce_tasks_sync(self):
        self.logger.info("⏳ Debounce: tasks sync triggered")

        async def schedule():
            await self._debounce(self.sync_tasks_up)

        try:
            loop = asyncio.get_running_loop()

            if self._tasks_debounce_task and not self._tasks_debounce_task.done():
                self._tasks_debounce_task.cancel()

            self._tasks_debounce_task = loop.create_task(schedule())

        except RuntimeError:
            asyncio.run(self._debounce(self.sync_tasks_up))

    # ============================================================
    # TASKS SYNC — REAL SYNC UP
    # ============================================================
    async def sync_tasks_up(self):
        self.logger.info("🚀 SYNC: Uploading tasks to Notion...")

        try:
            for task in self.tasks.get_all_tasks():

                # CREATE NEW TASK
                if not task.notion_id:
                    self.logger.info(f"📌 Creating new Notion task: {task.title}")

                    payload = {
                        "parent": {"database_id": self.tasks_db_id},
                        "properties": {
                            "Name": {"title": [{"text": {"content": task.title}}]},
                            "Status": {"select": {"name": task.status}},
                            "Priority": {"select": {"name": task.priority}} if task.priority else None,
                            "Deadline": {"date": {"start": task.deadline}} if task.deadline else {"date": None},
                            "Goal": {"relation": [{"id": task.goal_id}]} if task.goal_id else {"relation": []},
                        }
                    }

                    created = await self.notion.create_page(payload)

                    if created.get("ok"):
                        task.notion_id = created["data"]["id"]
                        self.logger.info(f"🆕 Task synced to Notion with ID: {task.notion_id}")

                    continue

                # UPDATE EXISTING TASK
                self.logger.info(f"♻️ Updating Notion task: {task.title}")

                update_payload = {
                    "properties": {
                        "Name": {"title": [{"text": {"content": task.title}}]},
                        "Status": {"select": {"name": task.status}},
                        "Priority": {"select": {"name": task.priority}} if task.priority else None,
                        "Deadline": {"date": {"start": task.deadline}} if task.deadline else {"date": None},
                        "Goal": {"relation": [{"id": task.goal_id}]} if task.goal_id else {"relation": []},
                    }
                }

                await self.notion.update_page(task.notion_id, update_payload)

            self.logger.info("✅ TASKS SYNC COMPLETE")

        except Exception as e:
            self.logger.error(f"❌ Task sync error: {e}")
