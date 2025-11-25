from fastapi import APIRouter, HTTPException, Depends
import os

from models.task_create import TaskCreate
from models.task_update import TaskUpdate

from dependencies import (
    get_tasks_service,
    get_notion_service
)

router = APIRouter(prefix="/tasks", tags=["Tasks"])


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
        "notion_id": getattr(task, "notion_id", None)
    }


# ============================================================
# CREATE TASK
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

        notion_res = await notion.create_page(notion_payload)

        if not notion_res["ok"]:
            return {"status": "notion_error", "detail": notion_res["error"]}

        notion_id = notion_res["data"]["id"]
        notion_url = notion_res["data"]["url"]

        # ⭐ Dodavanje taska u lokalni DB SA notion_id
        local_task = tasks_service.create_task(
            payload,
            notion_id=notion_id
        )

        return {
            "status": "created",
            "local": to_resp(local_task),
            "notion_page_id": notion_id,
            "notion_url": notion_url
        }

    except Exception as e:
        raise HTTPException(500, f"Task creation failed: {e}")


# ============================================================
# LIST TASKS
# ============================================================
@router.get("/all")
async def list_tasks(tasks_service=Depends(get_tasks_service)):
    return {"tasks": [to_resp(t) for t in tasks_service.get_all()]}


# ============================================================
# UPDATE TASK
# ============================================================
@router.patch("/{task_id}")
async def update_task(task_id: str, updates: TaskUpdate, tasks_service=Depends(get_tasks_service)):
    try:
        task = tasks_service.update_task(task_id, updates)
        return {"status": "updated", "task": to_resp(task)}
    except ValueError as e:
        raise HTTPException(404, str(e))


# ============================================================
# DELETE TASK (LOCAL + NOTION)
# ============================================================
@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    tasks_service=Depends(get_tasks_service),
    notion=Depends(get_notion_service)
):
    try:
        deleted = tasks_service.delete_task(task_id)

        notion_status = "skip"

        if hasattr(deleted, "notion_id") and deleted.notion_id:
            try:
                res = await notion.delete_page(deleted.notion_id)
                notion_status = "archived" if res["ok"] else res["error"]
            except Exception as e:
                notion_status = f"failed: {e}"

        return {
            "status": "deleted",
            "task": to_resp(deleted),
            "notion": notion_status
        }

    except ValueError as e:
        raise HTTPException(404, str(e))