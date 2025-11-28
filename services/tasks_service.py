from typing import List
from datetime import datetime

from models.task_model import TaskModel
from models.task_create import TaskCreate
from models.task_update import TaskUpdate

from integrations.notion_client import NotionClient
from utils.helpers import generate_uuid


notion = NotionClient()


# =====================================================
# CREATE SINGLE TASK
# =====================================================
def create_task(data: TaskCreate) -> TaskModel:
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

    notion.create_task(task)

    return task


# =====================================================
# UPDATE TASK
# =====================================================
def update_task(task_id: str, data: TaskUpdate):
    updated = notion.update_task(task_id, data)
    return updated


# =====================================================
# DELETE TASK
# =====================================================
def delete_task(task_id: str):
    notion.delete_task(task_id)
    return {"deleted": True}


# =====================================================
# GET ALL TASKS
# =====================================================
def get_all_tasks() -> List[TaskModel]:
    return notion.get_all_tasks()


# =====================================================
# BATCH CREATE — V4.3
# =====================================================
def create_tasks_batch(tasks: List[TaskCreate]) -> List[TaskModel]:
    created = []
    for t in tasks:
        item = create_task(t)
        created.append(item)
    return created
