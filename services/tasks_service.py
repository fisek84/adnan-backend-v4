from typing import List
from datetime import datetime

# =====================================================
# LEGACY WRAPPER — REQUIRED BY dependencies.py
# =====================================================
class TasksService:
    """
    Legacy compatibility class.
    The backend imports this class in dependencies.py,
    so we provide an empty wrapper to avoid ImportError.
    Actual logic lives in functional API below.
    """
    pass


from models.task_model import TaskModel
from models.task_create import TaskCreate
from models.task_update import TaskUpdate

from services.notion_service import get_notion_service
from utils.helpers import generate_uuid


# =====================================================
# CREATE SINGLE TASK
# =====================================================
def create_task(data: TaskCreate) -> TaskModel:
    notion = get_notion_service()

    task_id = generate_uuid()
    now = datetime.utcnow()

    task = TaskModel(
        id=task_id,
        notion_id=None,
        title=data.title,
        description=data.description,
        goal_id=data.goal_id,
        deadline=data.deadline,
        priority=data.priority,
        status="pending",
        order=0,
        created_at=now,
        updated_at=now,
    )

    # Notion sync call
    notion.create_task(task)

    return task


# =====================================================
# UPDATE TASK
# =====================================================
def update_task(task_id: str, data: TaskUpdate):
    notion = get_notion_service()
    return notion.update_task(task_id, data)


# =====================================================
# DELETE TASK
# =====================================================
def delete_task(task_id: str):
    notion = get_notion_service()
    notion.delete_task(task_id)
    return {"deleted": True}


# =====================================================
# GET ALL TASKS
# =====================================================
def get_all_tasks() -> List[TaskModel]:
    notion = get_notion_service()
    return notion.get_all_tasks()


# =====================================================
# BATCH CREATE
# =====================================================
def create_tasks_batch(tasks: List[TaskCreate]) -> List[TaskModel]:
    created = []
    for t in tasks:
        created.append(create_task(t))
    return created