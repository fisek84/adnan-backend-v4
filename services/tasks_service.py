from typing import List
from datetime import datetime

from models.task_model import TaskModel
from models.task_create import TaskCreate
from models.task_update import TaskUpdate

from services.notion_service import get_notion_service
from utils.helpers import generate_uuid


# =====================================================
# REQUIRED DUMMY CLASS (dependencies.py expects it)
# =====================================================
class TasksService:
    pass


# =====================================================
# CREATE SINGLE TASK
# =====================================================
async def create_task(data: TaskCreate) -> TaskModel:
    notion = get_notion_service()

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


# =====================================================
# UPDATE TASK
# =====================================================
async def update_task(page_id: str, data: TaskUpdate):
    notion = get_notion_service()
    return await notion.update_task(page_id, data)


# =====================================================
# DELETE TASK
# =====================================================
async def delete_task(page_id: str):
    notion = get_notion_service()
    await notion.delete_task(page_id)
    return {"deleted": True}


# =====================================================
# GET ALL TASKS
# =====================================================
async def get_all_tasks() -> List[TaskModel]:
    notion = get_notion_service()
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
                created_at=datetime.utcnow(),  # Notion nema timestamp
                updated_at=datetime.utcnow(),
            )
        )

    return tasks


# =====================================================
# BATCH CREATE
# =====================================================
async def create_tasks_batch(items: List[TaskCreate]) -> List[TaskModel]:
    created = []
    for t in items:
        created.append(await create_task(t))
    return created