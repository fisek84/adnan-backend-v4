import asyncio


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
        self._sync_projects_task = None

    def add_project_for_sync(self, project, delete=False):
        print(f"🔄 [SYNC] Queued project: {project.title}")
        if self._sync_projects_task and not self._sync_projects_task.done():
            self._sync_projects_task.cancel()
        self._sync_projects_task = asyncio.create_task(
            self._debounce(self.sync_projects_up)
        )

    async def _debounce(self, fn):
        try:
            await asyncio.sleep(self._delay)
            await fn()
        except asyncio.CancelledError:
            pass

    async def get_all_projects_from_notion(self):
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
        print("📥 Loading projects from Notion...")

        remote = await self.get_all_projects_from_notion()
        if not remote.get("ok"):
            print("⚠️ Failed loading Notion projects")
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

        print(f"📁 Loaded {len(results)} projects from Notion")

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
        print("🚀 SYNC: Uploading projects to Notion...")

        for p in self.projects.get_all():
            p_dict = self.projects.to_dict(p)
            props = self.map_local_project_to_notion(p_dict)

            # NOVA STRANICA
            if not p.notion_id:
                print("📌 Creating new Notion page:", p.title)
                created = await self.notion.create_project(p)
                if created.get("ok"):
                    new_id = created["data"]["id"]
                    self.projects._replace_id(p.id, new_id)
                continue

            # AŽURIRANJE
            print("♻️ Updating page:", p.title)
            await self.notion.update_page(p.notion_id, {"properties": props})

        print("✅ SYNC COMPLETE")
