from typing import List
from datetime import datetime

from models.task_model import TaskModel
from models.task_create import TaskCreate
from models.task_update import TaskUpdate

from dependencies import get_notion_service   # ← OVO JE KLJUČ !!!
from utils.helpers import generate_uuid


class TasksService:
    pass


async def create_task(data: TaskCreate) -> TaskModel:
    notion = get_notion_service()
    if notion is None:
        raise RuntimeError("NotionService not registered (DI error).")

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

    await notion.create_task(task)
    return task


async def update_task(page_id: str, data: TaskUpdate):
    notion = get_notion_service()
    if notion is None:
        raise RuntimeError("NotionService not registered (DI error).")

    return await notion.update_task(page_id, data)


async def delete_task(page_id: str):
    notion = get_notion_service()
    if notion is None:
        raise RuntimeError("NotionService not registered (DI error).")

    await notion.delete_task(page_id)
    return {"deleted": True}


async def get_all_tasks() -> List[TaskModel]:
    notion = get_notion_service()
    if notion is None:
        raise RuntimeError("NotionService not registered (DI error).")

    raw = await notion.get_all_tasks()
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


async def create_tasks_batch(items: List[TaskCreate]) -> List[TaskModel]:
    return [await create_task(t) for t in items]