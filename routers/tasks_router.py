from fastapi import APIRouter, HTTPException, Depends
import os

from models.task_create import TaskCreate
from models.task_update import TaskUpdate

from dependencies import get_tasks_service, get_notion_service


router = APIRouter(prefix="/tasks", tags=["Tasks"])


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
# CREATE TASK (FIXED)
# ============================================================

@router.post("/create")
async def create_task(
    payload: TaskCreate,
    tasks_service=Depends(get_tasks_service),
    notion=Depends(get_notion_service)
):
    try:
        db_id = os.getenv("NOTION_TASKS_DB_ID")

        # 🔵 FIXED — correct Notion API format
        notion_payload = {
            "parent": {"database_id": db_id},
            "properties": {
                "Name": {
                    "title": [{"text": {"content": payload.title}}]
                }
            }
        }

        res = await notion.create_page(notion_payload)

        # local
        local = tasks_service.create_task(payload)

        return {
            "status": "created",
            "local": to_resp(local),
            "notion_page_id": res.get("id"),
            "notion_url": res.get("url")
        }

    except Exception as e:
        raise HTTPException(500, f"Task creation failed: {str(e)}")


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