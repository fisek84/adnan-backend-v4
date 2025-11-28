from typing import List, Optional
from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskResponse
from integrations.notion_client import NotionClient
from utils.helpers import generate_uuid

# Pretpostavka: koristiš SQLite kroz tasks.db ili lokalnu listu (kao u tvom projektu)
# Ako koristiš drugu implementaciju, create_task već postoji – koristimo ga rješenjem ispod.

notion = NotionClient()

# ===============================
# SINGLE TASK CREATE
# ===============================
def create_task(data: TaskCreate) -> TaskResponse:
    """
    Kreira jedan task u lokalnoj bazi + vraća TaskResponse.
    """
    task_id = generate_uuid()

    # Lokalni objekt
    task = TaskResponse(
        id=task_id,
        title=data.title,
        description=data.description,
        goal_id=data.goal_id,
        deadline=data.deadline,
        priority=data.priority,
        status="pending",
        order=0
    )

    # Snimi u Notion
    notion.create_task(task)

    return task


# ===============================
# UPDATE
# ===============================
def update_task(task_id: str, data: TaskUpdate):
    updated = notion.update_task(task_id, data)
    return updated


# ===============================
# DELETE
# ===============================
def delete_task(task_id: str):
    notion.delete_task(task_id)
    return {"deleted": True}


# ===============================
# GET ALL
# ===============================
def get_all_tasks() -> List[TaskResponse]:
    return notion.get_all_tasks()


# ===============================
# BATCH — NOVO u v4.3
# ===============================
def create_tasks_batch(tasks: List[TaskCreate]):
    """
    Kreira više taskova odjednom.
    Ovdje backend NIJE ograničen na Notion rate-limit, jer šaljemo taskove jedan po jedan.
    """
    created = []

    for t in tasks:
        item = create_task(t)
        created.append(item)

    return created