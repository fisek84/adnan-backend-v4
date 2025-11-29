from typing import List
from datetime import datetime

from models.task_model import TaskModel
from models.task_create import TaskCreate
from models.task_update import TaskUpdate

from services.notion_service import NotionService
from utils.helpers import generate_uuid


class TasksService:
    def __init__(self, notion_service: NotionService):
        self.notion = notion_service
        self.local_tasks = {}  # required for sync service

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

        # save locally for sync
        self.local_tasks[task_id] = task

        await self.notion.create_task(task)
        return task

    # ------------------------------------------------------
    # UPDATE
    # ------------------------------------------------------
    async def update_task(self, page_id: str, data: TaskUpdate):
        return await self.notion.update_task(page_id, data)

    # ------------------------------------------------------
    # DELETE
    # ------------------------------------------------------
    async def delete_task(self, page_id: str):
        if page_id in self.local_tasks:
            self.local_tasks.pop(page_id)

        # FIX: NotionService has delete_page(), not delete_task()
        await self.notion.delete_page(page_id)

        return {"deleted": True}

    # ------------------------------------------------------
    # REQUIRED BY SYNC SERVICE
    # ------------------------------------------------------
    def get_all(self) -> List[TaskModel]:
        """Returns local in-memory tasks for sync."""
        return list(self.local_tasks.values())

    def _to_dict(self, task: TaskModel) -> dict:
        """Required by sync service to map task to dict."""
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
        """Required for sync—update local primary key after Notion creates a page."""
        if old_id in self.local_tasks:
            task = self.local_tasks.pop(old_id)
            task.id = new_id
            task.notion_id = new_id
            self.local_tasks[new_id] = task

    # ------------------------------------------------------
    # GET ALL FROM NOTION (normal API use)
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