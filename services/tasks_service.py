from typing import List
from datetime import datetime

from fastapi import Depends

from models.task_model import TaskModel
from models.task_create import TaskCreate
from models.task_update import TaskUpdate

from services.notion_service import NotionService
from utils.helpers import generate_uuid


class TasksService:
    def __init__(self, notion_service: NotionService):
        self.notion = notion_service

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
        await self.notion.delete_task(page_id)
        return {"deleted": True}

    # ------------------------------------------------------
    # GET ALL
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