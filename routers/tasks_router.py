from fastapi import APIRouter, HTTPException, Depends
import os

from models.task_create import TaskCreate
from models.task_update import TaskUpdate

from dependencies import (
    get_tasks_service,
    get_notion_service
)

router = APIRouter(prefix="/tasks", tags=["Tasks"])


# ============================================================
# TRANSFORMER
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
# CREATE TASK (SAFE + NOTION V2)
# ============================================================
@router.post("/create")
async def create_task(
    payload: TaskCreate,
    tasks_service=Depends(get_tasks_service),
    notion=Depends(get_notion_service)
):
    try:
        db_id = os.getenv("NOTION_TASKS_DB_ID")

        notion_payload = {
            "parent": {"database_id": db_id},
            "properties": {
                "Name": {
                    "title": [{"text": {"content": payload.title}}]
                }
            }
        }

        # SAFE Notion API
        notion_res = await notion.create_page(notion_payload)

        if not notion_res["ok"]:
            return {
                "status": "notion_error",
                "detail": notion_res["error"]
            }

        notion_id = notion_res["data"]["id"]
        notion_url = notion_res["data"]["url"]

        # LOCAL DB
        new_task = tasks_service.create_task(payload)

        return {
            "status": "created",
            "local": to_resp(new_task),
            "notion_page_id": notion_id,
            "notion_url": notion_url
        }

    except Exception as e:
        raise HTTPException(500, f"Task creation failed: {e}")


# ============================================================
# UPDATE TASK
# ============================================================
@router.patch("/{task_id}")
async def update_task(
    task_id: str,
    data: TaskUpdate,
    tasks_service=Depends(get_tasks_service)
):
    try:
        updated = tasks_service.update_task(task_id, data)
        return {"status": "updated", "task": to_resp(updated)}
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