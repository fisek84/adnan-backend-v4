import asyncio
import aiohttp


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
        self._goals_task = None
        self._tasks_task = None
        self._projects_task = None

        self.loop = None

    # =====================================================================
    # DEBOUNCE HELPERS
    # =====================================================================
    async def start(self):
        self.loop = asyncio.get_running_loop()

    async def _debounce(self, fn):
        try:
            await asyncio.sleep(self._delay)
            await fn()
        except asyncio.CancelledError:
            pass
        except Exception:
            pass

    async def debounce_goals_sync(self):
        if self._goals_task and not self._goals_task.done():
            self._goals_task.cancel()
        self._goals_task = asyncio.create_task(self._debounce(self.sync_goals_up))

    async def debounce_tasks_sync(self):
        if self._tasks_task and not self._tasks_task.done():
            self._tasks_task.cancel()
        self._tasks_task = asyncio.create_task(self._debounce(self.sync_tasks_up))

    async def debounce_projects_sync(self):
        if self._projects_task and not self._projects_task.done():
            self._projects_task.cancel()
        self._projects_task = asyncio.create_task(self._debounce(self.sync_projects_up))

    # =====================================================================
    # PROJECTS — NOTION → BACKEND
    # =====================================================================
    async def get_all_projects_from_notion(self):
        return await self.notion.query_database(self.projects_db_id)

    def map_project_page(self, page):
        props = page.get("properties", {})

        def safe(prop_name, kind):
            prop = props.get(prop_name)
            if not prop:
                return None
            try:
                if kind == "title":
                    return prop["title"][0]["plain_text"] if prop.get("title") else ""
                if kind == "text":
                    return prop["rich_text"][0]["plain_text"] if prop.get("rich_text") else ""
                if kind == "select":
                    return prop["select"]["name"] if prop.get("select") else None
                if kind == "date":
                    return prop["date"]["start"] if prop.get("date") else None
                if kind == "relation":
                    rel = prop.get("relation") or []
                    return [r["id"].replace("-", "") for r in rel]
            except Exception:
                return None
            return None

        # ================================================
        # 🔥 AUTOMATSKA VALIDACIJA NASLOVA (TVOJ ZAHTJEV)
        # ================================================
        title = safe("Project Name", "title")
        if not title or title.strip() == "":
            raise ValueError(
                f"Project in Notion (ID: {page['id']}) has no title. Please add a title."
            )

        return {
            "id": page["id"].replace("-", ""),
            "notion_id": page["id"],

            "title": title,
            "description": safe("Description", "text"),
            "status": safe("Status", "select") or "active",
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

            # SAFE DEFAULT
            "progress": 0,
        }

    async def load_projects_into_backend(self):

        remote = await self.get_all_projects_from_notion()
        if not remote.get("ok"):
            print("⚠️ Could not load projects from Notion")
            return

        results = remote["data"]["results"]

        for page in results:
            try:
                mapped = self.map_project_page(page)
            except ValueError as e:
                # 🔥 UMJESTO RUŠENJA — SAMO UPOZORI
                print(f"⚠️ Notion sync warning: {str(e)}")
                continue

            if mapped["id"] in self.projects.projects:
                self.projects.projects[mapped["id"]].tasks = mapped["tasks"]
                continue

            self.projects.create_project(
                data=self.projects.to_create_model(mapped),
                forced_id=mapped["id"],
                notion_id=mapped["notion_id"]
            )

        print(f"📁 Loaded {len(results)} projects into backend")

    # =====================================================================
    # PROJECTS — BACKEND → NOTION
    # =====================================================================
    def map_local_project_to_notion(self, p: dict):

        def wrap(x):
            return {"rich_text": [{"text": {"content": x or ""}}]}

        return {
            "Project Name": {"title": [{"text": {"content": p.get("title") or ""}}]},
            "Description": wrap(p.get("description")),
            "Status": {"select": {"name": p.get("status")}},
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
        for p in self.projects.get_all():
            p_dict = self.projects.to_dict(p)
            props = self.map_local_project_to_notion(p_dict)

            if not p.notion_id:
                created = await self.notion.create_page({
                    "parent": {"database_id": self.projects_db_id},
                    "properties": props
                })
                if created.get("ok"):
                    new_id = created["data"]["id"]
                    self.projects._replace_id(p.id, new_id)
                continue

            await self.notion.update_page(p.notion_id, {"properties": props})

    # =====================================================================
    # UNUSED (BUT REQUIRED FOR API CONTRACT)
    # =====================================================================
    async def sync_goals_up(self):
        pass

    async def sync_tasks_up(self):
        pass
