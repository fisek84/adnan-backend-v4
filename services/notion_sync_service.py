# services/notion_sync_service.py
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

    async def start(self):
        self.loop = asyncio.get_running_loop()

    # --------------------------------------------------------
    # DEBOUNCE LAYERS
    # --------------------------------------------------------
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
        props = page["properties"]

        def safe(prop, kind):
            try:
                if kind == "title":
                    return prop["title"][0]["plain_text"] if prop["title"] else ""
                if kind == "text":
                    return prop["rich_text"][0]["plain_text"] if prop["rich_text"] else ""
                if kind == "select":
                    return prop["select"]["name"] if prop["select"] else None
                if kind == "date":
                    return prop["date"]["start"] if prop["date"] else None
            except:
                return None
            return None

        return {
            "id": page["id"].replace("-", ""),
            "notion_id": page["id"],

            "title": safe(props["Project Name"], "title"),
            "description": safe(props["Description"], "text"),
            "status": safe(props["Status"], "select"),
            "category": safe(props["Category"], "select"),
            "priority": safe(props["Priority"], "select"),

            "start_date": safe(props["Start Date"], "date"),
            "deadline": safe(props["Target Deadline"], "date"),

            "project_type": safe(props["Project Type"], "select"),
            "summary": safe(props["Summary"], "text"),
            "next_step": safe(props["Next Step"], "text"),

            "goal_id": (
                props["Primary Goal"]["relation"][0]["id"].replace("-", "")
                if props["Primary Goal"]["relation"] else None
            ),

            "parent_id": (
                props["Parent Project"]["relation"][0]["id"].replace("-", "")
                if props["Parent Project"]["relation"] else None
            ),

            "agents": [a["id"] for a in props["Agent Exchange DB"]["relation"]]
                      if props["Agent Exchange DB"]["relation"] else [],

            # 🔥 TASKS DB — REFERENCE TO MASTER TASKS DB (THIS IS CRITICAL)
            "tasks": [t["id"] for t in props["Tasks DB"]["relation"]]
                     if props["Tasks DB"]["relation"] else [],

            "handled_by": safe(props["Handled By"], "text"),
        }

    async def load_projects_into_backend(self):
        remote = await self.get_all_projects_from_notion()
        if not remote["ok"]:
            print("⚠️ Cannot load Projects DB from Notion")
            return

        pages = remote["data"]["results"]

        for page in pages:
            mapped = self.map_project_page(page)

            if mapped["id"] in self.projects.projects:
                # Update tasks list from Notion
                self.projects.projects[mapped["id"]].tasks = mapped["tasks"]
                continue

            self.projects.create_project(
                data=self.projects.to_create_model(mapped),
                forced_id=mapped["id"],
                notion_id=mapped["notion_id"]
            )

        print(f"📁 Loaded {len(pages)} projects from Notion → backend")

    # =====================================================================
    # PROJECTS — BACKEND → NOTION
    # =====================================================================
    def map_local_project_to_notion(self, p: dict):
        def wrap(val):
            return {"rich_text": [{"text": {"content": val or ""}}]}

        return {
            "Project Name": {
                "title": [{"text": {"content": p.get("title") or ""}}]
            },
            "Description": wrap(p.get("description")),
            "Status": {"select": {"name": p["status"]}} if p.get("status") else {"select": None},
            "Category": {"select": {"name": p["category"]}} if p.get("category") else {"select": None},
            "Priority": {"select": {"name": p["priority"]}} if p.get("priority") else {"select": None},

            "Start Date": {"date": {"start": p["start_date"]}} if p.get("start_date") else {"date": None},
            "Target Deadline": {"date": {"start": p["deadline"]}} if p.get("deadline") else {"date": None},

            "Project Type": {"select": {"name": p["project_type"]}} if p.get("project_type") else {"select": None},

            "Summary": wrap(p.get("summary")),
            "Next Step": wrap(p.get("next_step")),

            "Primary Goal": (
                {"relation": [{"id": p["goal_id"]}]}
                if p.get("goal_id") else {"relation": []}
            ),
            "Parent Project": (
                {"relation": [{"id": p["parent_id"]}]}
                if p.get("parent_id") else {"relation": []}
            ),
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
                if created["ok"]:
                    new_id = created["data"]["id"]
                    old = p.id
                    p.notion_id = new_id
                    self.projects._replace_id(old, new_id)
                continue

            await self.notion.update_page(p.notion_id, {"properties": props})

        # DELETE SYNC
        try:
            local_ids = {p.notion_id for p in self.projects.get_all() if p.notion_id}

            remote = await self.notion.query_database(self.projects_db_id)
            if not remote["ok"]:
                return

            for page in remote["data"]["results"]:
                if page["id"] not in local_ids:
                    await self.notion.update_page(page["id"], {"archived": True})

        except Exception as e:
            print("⚠️ Error syncing projects:", str(e))

    # =====================================================================
    # GOALS & TASKS SYNC (same as before, unchanged)
    # =====================================================================

    # ... (TASKS + GOALS CODE YOU ALREADY HAVE — ostaje identično)
