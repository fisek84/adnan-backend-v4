# services/tasks_service.py

from typing import List
from datetime import datetime

from models.task_model import TaskModel
from models.task_create import TaskCreate
from models.task_update import TaskUpdate

from services.notion_service import NotionService
from utils.helpers import generate_uuid
from services.auto_assign_engine import AutoAssignEngine


class TasksService:
    def __init__(self, notion_service: NotionService):
        self.notion = notion_service
        self.local_tasks = {}  # required for sync service
        self.projects_db_id = None   # sync će postaviti ovo kasnije

    # ------------------------------------------------------
    # CREATE
    # ------------------------------------------------------
    async def create_task(self, data: TaskCreate) -> TaskModel:
        task_id = generate_uuid()
        now = datetime.utcnow()

        task = TaskModel(
            id=task_id,
            notion_id=None,
            title=data.title,
            description=data.description or "",
            goal_id=data.goal_id,
            deadline=data.deadline,
            priority=data.priority,
            status="pending",
            order=0,
            created_at=now,
            updated_at=now,
        )

        # save locally
        self.local_tasks[task_id] = task

        # create in notion → returns page_id
        notion_page_id = await self.notion.create_task(task)

        if isinstance(notion_page_id, str):
            task.notion_id = notion_page_id
            self.local_tasks[task_id] = task

        # AUTO-ASSIGN SYSTEM
        if task.notion_id:
            await self._auto_assign_goal_if_missing(task.notion_id)
            await self._auto_assign_project_if_missing(task.notion_id)
            await self._auto_assign_goal_from_project_if_missing(task.notion_id)
            await self._auto_assign_project_if_missing_advanced(task.notion_id)
            await self._auto_assign_goal_from_project_advanced(task.notion_id)

        return task

    # ------------------------------------------------------
    # UPDATE
    # ------------------------------------------------------
    async def update_task(self, page_id: str, data: TaskUpdate):

        # primary update
        result = await self.notion.update_task(page_id, data)

        # AUTO-ASSIGN SYSTEM
        await self._auto_assign_goal_if_missing(page_id)
        await self._auto_assign_project_if_missing(page_id)
        await self._auto_assign_goal_from_project_if_missing(page_id)
        await self._auto_assign_project_if_missing_advanced(page_id)
        await self._auto_assign_goal_from_project_advanced(page_id)

        return result

    # ------------------------------------------------------
    # DELETE  (FIXED & WORKING VERSION)
    # ------------------------------------------------------
    async def delete_task(self, task_id: str):

        notion_id = None

        # A) direct match by local id
        if task_id in self.local_tasks:
            notion_id = self.local_tasks[task_id].notion_id
            self.local_tasks.pop(task_id)

        else:
            # B) maybe the user sent the notion_id directly
            for tid, t in list(self.local_tasks.items()):
                if t.notion_id == task_id:
                    notion_id = t.notion_id
                    self.local_tasks.pop(tid)
                    break

        # fallback (if nothing found)
        if not notion_id:
            notion_id = task_id

        # Archive in Notion = REAL delete
        await self.notion.archive_page(notion_id)

        return {"deleted": True}

    # ------------------------------------------------------
    # GET LOCAL
    # ------------------------------------------------------
    def get_all(self) -> List[TaskModel]:
        return list(self.local_tasks.values())

    def _to_dict(self, task: TaskModel) -> dict:
        return {
            "id": task.id,
            "notion_id": task.notion_id,
            "title": task.title,
            "description": task.description,
            "goal_id": task.goal_id,
            "deadline": task.deadline,
            "priority": task.priority,
            "status": task.status,
            "order": task.order,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }

    def _replace_id(self, old_id: str, new_id: str):
        if old_id in self.local_tasks:
            task = self.local_tasks.pop(old_id)
            task.id = new_id
            task.notion_id = new_id
            self.local_tasks[new_id] = task

    # ------------------------------------------------------
    # GET ALL FROM NOTION
    # ------------------------------------------------------
    async def get_all_tasks(self) -> List[TaskModel]:
        raw = await self.notion.get_all_tasks()
        tasks = []

        for item in raw:
            tasks.append(
                TaskModel(
                    id=item["id"],
                    notion_id=item["notion_id"],
                    title=item["title"],
                    description=item["description"],
                    goal_id=item["goal_id"],
                    deadline=item["deadline"],
                    priority=item["priority"],
                    status=item["status"],
                    order=item["order"],
                    created_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )

        return tasks

    # ------------------------------------------------------
    # BATCH CREATE
    # ------------------------------------------------------
    async def create_tasks_batch(self, items: List[TaskCreate]) -> List[TaskModel]:
        results = []
        for t in items:
            results.append(await self.create_task(t))
        return results

    # ======================================================================
    # AUTO ASSIGN — GOAL (DIRECT)
    # ======================================================================
    async def _auto_assign_goal_if_missing(self, page_id: str):
        page = await self.notion.get_page(page_id)
        if not page or "properties" not in page:
            return

        goal_prop = page["properties"].get("Goal", {})
        if goal_prop.get("relation"):
            return

        resolved_goal = AutoAssignEngine.get_effective_goal_id(page)
        if not resolved_goal:
            return

        update = TaskUpdate(goal_id=resolved_goal)
        await self.update_task(page_id, update)

    # ======================================================================
    # AUTO ASSIGN — PROJECT (DIRECT)
    # ======================================================================
    async def _auto_assign_project_if_missing(self, page_id: str):
        page = await self.notion.get_page(page_id)
        if not page or "properties" not in page:
            return

        proj_prop = page["properties"].get("Project", {})
        if proj_prop.get("relation"):
            return

        resolved_proj = AutoAssignEngine.get_effective_project_id(page)
        if not resolved_proj:
            return

        update = TaskUpdate(project_id=resolved_proj)
        await self.update_task(page_id, update)

    # ======================================================================
    # AUTO ASSIGN — GOAL FROM PROJECT BASIC
    # ======================================================================
    async def _auto_assign_goal_from_project_if_missing(self, page_id: str):
        page = await self.notion.get_page(page_id)
        if not page:
            return

        if AutoAssignEngine.get_goal_id_for_task(page):
            return

        proj_id = AutoAssignEngine.get_project_id_for_task(page)
        if not proj_id:
            return

        project_page = await self.notion.get_page(proj_id)
        if not project_page:
            return

        resolved = AutoAssignEngine.get_primary_goal_for_project(project_page)
        if not resolved:
            return

        update = TaskUpdate(goal_id=resolved)
        await self.update_task(page_id, update)

    # ======================================================================
    # AUTO ASSIGN — PROJECT ADVANCED
    # ======================================================================
    async def _auto_assign_project_if_missing_advanced(self, page_id: str):
        if not self.projects_db_id:
            return

        page = await self.notion.get_page(page_id)
        if not page:
            return

        direct = AutoAssignEngine.get_project_id_for_task(page)
        if direct:
            return

        remote = await self.notion.query_database(self.projects_db_id)
        if not remote["ok"]:
            return

        for proj_page in remote["data"]["results"]:
            task_ids = AutoAssignEngine.get_task_ids_from_project(proj_page)
            if page_id.replace("-", "") in task_ids:
                update = TaskUpdate(project_id=proj_page["id"])
                await self.update_task(page_id, update)
                return

    # ======================================================================
    # AUTO ASSIGN — GOAL FROM PROJECT ADVANCED
    # ======================================================================
    async def _auto_assign_goal_from_project_advanced(self, page_id: str):
        page = await self.notion.get_page(page_id)
        if not page:
            return

        already_goal = AutoAssignEngine.get_goal_id_for_task(page)
        if already_goal:
            return

        proj_id = AutoAssignEngine.get_project_id_for_task(page)
        if not proj_id:
            return

        project_page = await self.notion.get_page(proj_id)
        if not project_page:
            return

        resolved = AutoAssignEngine.resolve_effective_goal(page, project_page)
        if not resolved:
            return

        update = TaskUpdate(goal_id=resolved)
        await self.update_task(page_id, update)


# -----------------------------------------------------------
# INTERNAL PASSIVE HOOK
# -----------------------------------------------------------
def _prepare_auto_assign(page_data: dict):
    return page_data
