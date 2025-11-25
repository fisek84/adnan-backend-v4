from fastapi import APIRouter, HTTPException, Depends
import os
import json
import requests

from models.task_create import TaskCreate
from models.task_update import TaskUpdate

# Injected in main.py
tasks_service_global = None

router = APIRouter(prefix="/tasks", tags=["Tasks"])

# ============================================================
# DEPENDENCY
# ============================================================

def get_tasks_service():
    if not tasks_service_global:
        raise HTTPException(500, "TasksService not initialized")
    return tasks_service_global

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
# CREATE TASK  (Notion + Local)
# ============================================================

@router.post("/create")
def create_task(payload: TaskCreate):
    try:
        NOTION_API_KEY = os.getenv("NOTION_API_KEY")
        TASKS_DB_ID = os.getenv("NOTION_TASKS_DB_ID")

        NOTION_HEADERS = {
            "Authorization": f"Bearer {NOTION_API_KEY}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28"
        }

        notion_payload = {
            "parent": {"database_id": TASKS_DB_ID},
            "properties": {
                "Name": {
                    "title": [{"text": {"content": payload.title}}]
                }
            }
        }

        notion_resp = requests.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            data=json.dumps(notion_payload)
        )

        if notion_resp.status_code != 200:
            raise HTTPException(notion_resp.status_code, notion_resp.text)

        notion_data = notion_resp.json()

        # Local task create
        if tasks_service_global:
            local_task = tasks_service_global.create_task(payload)
            local_data = to_resp(local_task)
        else:
            local_data = None

        return {
            "status": "created",
            "task_title": payload.title,
            "local": local_data,
            "notion_page_id": notion_data["id"],
            "notion_url": notion_data["url"]
        }

    except Exception as e:
        raise HTTPException(500, f"Failed to create task: {e}")

# ============================================================
# UPDATE TASK
# ============================================================

@router.patch("/{task_id}")
def update_task(task_id: str, updates: TaskUpdate, tasks_service=Depends(get_tasks_service)):
    try:
        task = tasks_service.update_task(task_id, updates)
        return {"status": "updated", "task": to_resp(task)}
    except ValueError as e:
        raise HTTPException(404, str(e))

# ============================================================
# LIST TASKS
# ============================================================

@router.get("/all")
def list_tasks(tasks_service=Depends(get_tasks_service)):
    return {"tasks": [to_resp(t) for t in tasks_service.get_all()]}

# AI alias
@router.get("/tasks/all")
async def get_all_tasks(tasks_service=Depends(get_tasks_service)):
    return {"tasks": [to_resp(t) for t in tasks_service.get_all()]}

# ============================================================
# DELETE TASK
# ============================================================

@router.delete("/{task_id}")
def delete_task(task_id: str, tasks_service=Depends(get_tasks_service)):
    try:
        deleted = tasks_service.delete_task(task_id)
        return {
            "status": "deleted",
            "task": to_resp(deleted)
        }
    except ValueError as e:
        raise HTTPException(404, str(e))
