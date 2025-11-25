from fastapi import APIRouter, HTTPException, Depends
import os

from models.task_create import TaskCreate
from models.task_update import TaskUpdate

# Injected in main.py
tasks_service_global = None
notion_service_global = None

router = APIRouter(prefix="/tasks", tags=["Tasks"])


# ============================================================
# DEPENDENCIES
# ============================================================

def get_tasks_service():
    if tasks_service_global is None:
        raise HTTPException(500, "TasksService not initialized")
    return tasks_service_global


def get_notion_service():
    if notion_service_global is None:
        raise HTTPException(500, "NotionService not initialized")
    return notion_service_global


# ============================================================
# RESPONSE TRANSFORMER
# ============================================================

def to_resp(task):
    return {
        "id": task.id,
        "title": task.title,
        "description": task.description,
        "goal_id": task.goal_id,
        "deadline": task.deadline,
        "priority": task.priority,
        "status": task.status,
        "order": task.order,
    }


# ============================================================
# CREATE TASK (Async, Notion + Local)
# ============================================================

@router.post("/create")
async def create_task(
    payload: TaskCreate,
    tasks_service=Depends(get_tasks_service),
    notion=Depends(get_notion_service)
):
    try:
        TASKS_DB_ID = os.getenv("NOTION_TASKS_DB_ID")

        notion_payload = {
            "parent": {"database_id": TASKS_DB_ID},
            "properties": {
                "Name": {
                    "title": [{"text": {"content": payload.title}}]
                }
            }
        }

        # Create in Notion
        notion_res = await notion.create_page(notion_payload)

        notion_id = notion_res.get("id")
        notion_url = notion_res.get("url")

        # Create in local DB
        local_task = tasks_service.create_task(payload)

        return {
            "status": "created",
            "local": to_resp(local_task),
            "notion_page_id": notion_id,
            "notion_url": notion_url
        }

    except Exception as e:
        raise HTTPException(500, f"Task creation failed: {str(e)}")


# ============================================================
# UPDATE TASK
# ============================================================

@router.patch("/{task_id}")
async def update_task(
    task_id: str,
    updates: TaskUpdate,
    tasks_service=Depends(get_tasks_service)
):
    try:
        task = tasks_service.update_task(task_id, updates)
        return {"status": "updated", "task": to_resp(task)}
    except ValueError as e:
        raise HTTPException(404, str(e))


# ============================================================
# LIST TASKS
# ============================================================

@router.get("/all")
async def list_tasks(tasks_service=Depends(get_tasks_service)):
    return {"tasks": [to_resp(t) for t in tasks_service.get_all()]}


# ============================================================
# DELETE TASK
# ============================================================

@router.delete("/{task_id}")
async def delete_task(task_id: str, tasks_service=Depends(get_tasks_service)):
    try:
        deleted = tasks_service.delete_task(task_id)
        return {"status": "deleted", "task": to_resp(deleted)}
    except ValueError as e:
        raise HTTPException(404, str(e))
