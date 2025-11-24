import asyncio
from typing import Any, Dict, List, Optional

class NotionSyncService:
    """
    Evolia Notion Sync Engine v4 — Robust sync engine
    """

    def __init__(
        self,
        notion_service,
        goals_service,
        tasks_service,
        goals_db_id: str,
        tasks_db_id: str
    ):
        self.notion = notion_service
        self.goals = goals_service
        self.tasks = tasks_service
        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id

        self._goals_db_task: Optional[asyncio.Task] = None
        self._tasks_db_task: Optional[asyncio.Task] = None
        self._delay = 0.25

    # ============================================================
    # DEBOUNCE
    # ============================================================
    async def debounce_goals_sync(self):
        self._cancel(self._goals_db_task)
        self._goals_db_task = asyncio.create_task(self._debounce(self.sync_goals_up))

    async def debounce_tasks_sync(self):
        self._cancel(self._tasks_db_task)
        self._tasks_db_task = asyncio.create_task(self._debounce(self.sync_tasks_up))

    async def _debounce(self, fn):
        try:
            await asyncio.sleep(self._delay)
            await fn()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print("[NotionSync] Debounce error:", e)

    @staticmethod
    def _cancel(task: Optional[asyncio.Task]):
        if task and not task.done():
            task.cancel()

    # ============================================================
    # INTERNAL HELPERS: ID REPLACEMENT
    # ============================================================
    def _replace_goal_id(self, old_id: str, new_id: str):
        try:
            g = self.goals.goals.pop(old_id, None)
            if g:
                g.id = new_id
                self.goals.goals[new_id] = g

            for other in list(self.goals.goals.values()):
                if other.parent_id == old_id:
                    other.parent_id = new_id
                other.children = [new_id if c == old_id else c for c in other.children]

            for t in list(self.tasks.tasks.values()):
                if t.goal_id == old_id:
                    t.goal_id = new_id

        except Exception as e:
            print("[NotionSync] _replace_goal_id error:", e)

    def _replace_task_id(self, old_id: str, new_id: str):
        try:
            t = self.tasks.tasks.pop(old_id, None)
            if t:
                t.id = new_id
                self.tasks.tasks[new_id] = t
        except Exception as e:
            print("[NotionSync] _replace_task_id error:", e)

    # ============================================================
    # SYNC UP (LOCAL → NOTION)
    # ============================================================
    async def sync_goals_up(self):
        for goal in list(self.goals.get_all()):
            try:
                props = self.map_local_goal_to_notion(self.goals.to_dict(goal))
            except Exception as e:
                print("[NotionSync] Error mapping goal to notion props:", e)
                continue

            notion_id = getattr(goal, "notion_id", None)

            if not notion_id:
                create = await self.notion.create_page(self.goals_db_id, props)
                if create.get("ok"):
                    new_id = create["data"]["id"]
                    goal.notion_id = new_id
                    old_id = goal.id
                    self._replace_goal_id(old_id, new_id)
                else:
                    print("[NotionSync] Goal create failed:", create.get("error"))
                continue

            update = await self.notion.update_page(notion_id, props)
            if update.get("ok"):
                continue

            if update.get("error"):
                print("[NotionSync] Goal update failed -> fallback create:", update["error"])

            create = await self.notion.create_page(self.goals_db_id, props)
            if create.get("ok"):
                new_id = create["data"]["id"]
                goal.notion_id = new_id
                old_id = goal.id
                self._replace_goal_id(old_id, new_id)
            else:
                print("[NotionSync] Goal create failed:", create.get("error"))

    async def sync_tasks_up(self):
        for task in list(self.tasks.get_all()):
            try:
                props = self.map_local_task_to_notion(self.tasks._to_dict(task))
            except Exception as e:
                print("[NotionSync] Error mapping task to notion props:", e)
                continue

            notion_id = getattr(task, "notion_id", None)

            if not notion_id:
                create = await self.notion.create_page(self.tasks_db_id, props)
                if create.get("ok"):
                    new_id = create["data"]["id"]
                    task.notion_id = new_id
                    old_id = task.id
                    self._replace_task_id(old_id, new_id)
                else:
                    print("[NotionSync] Task create failed:", create.get("error"))
                continue

            update = await self.notion.update_page(notion_id, props)
            if update.get("ok"):
                continue

            if update.get("error"):
                print("[NotionSync] Task update failed -> fallback create:", update["error"])

            create = await self.notion.create_page(self.tasks_db_id, props)
            if create.get("ok"):
                new_id = create["data"]["id"]
                task.notion_id = new_id
                old_id = task.id
                self._replace_task_id(old_id, new_id)
            else:
                print("[NotionSync] Task create failed:", create.get("error"))

    # ============================================================
    # SYNC DOWN (NOTION → LOCAL)
    # ============================================================
    async def sync_goals_down(self):
        pages = await self._fetch_all(self.goals_db_id)
        for page in pages:
            mapped = self.map_notion_goal_to_local(page)
            try:
                self.goals.sync_from_notion(mapped)
            except Exception as e:
                print("[NotionSync] sync_goals_down error:", e)

    async def sync_tasks_down(self):
        pages = await self._fetch_all(self.tasks_db_id)
        for page in pages:
            mapped = self.map_notion_task_to_local(page)
            try:
                self.tasks.sync_from_notion(mapped)
            except Exception as e:
                print("[NotionSync] sync_tasks_down error:", e)

    # ============================================================
    # FETCH ALL FROM DB
    # ============================================================
    async def _fetch_all(self, db_id: str):
        results = []
        cursor = None

        while True:
            payload = {"start_cursor": cursor} if cursor else {}
            resp = await self.notion.query_database(db_id, payload)

            if not resp.get("ok"):
                print("[NotionSync] fetch_all error:", resp.get("error"))
                break

            data = resp["data"]
            results.extend(data.get("results", []))

            if not data.get("has_more"):
                break

            cursor = data.get("next_cursor")

        return results

    # ============================================================
    # HELPERS
    # ============================================================
    def _props(self, page):
        return page.get("properties", {})

    def _id(self, page):
        return page.get("id", "")

    def _text(self, props, key):
        try:
            return props[key]["title"][0]["plain_text"]
        except:
            return ""

    def _rich(self, props, key):
        try:
            return props[key]["rich_text"][0]["plain_text"]
        except:
            return ""

    def _select(self, props, key):
        try:
            return props[key]["select"]["name"]
        except:
            return None

    def _number(self, props, key):
        try:
            return props[key]["number"]
        except:
            return 0

    def _date(self, props, key):
        try:
            return props[key]["date"]["start"]
        except:
            return None

    def _rels(self, props, key):
        try:
            return [item["id"] for item in props[key]["relation"]]
        except:
            return []