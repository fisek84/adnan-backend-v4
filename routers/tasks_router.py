from fastapi import APIRouter, HTTPException
from typing import Optional

from models.task_create import TaskCreate
from models.task_update import TaskUpdate

import os
import json
import requests

# Will be injected from main.py
tasks_service_global = None

router = APIRouter(prefix="/tasks", tags=["Tasks"])

# ============================================================
# RESPONSE TRANSFORMER (LOCAL)
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
# TASK CREATE — NOW SENDS TO NOTION TASKS DB
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

        # Minimal Notion Task payload (Name property)
        notion_payload = {
            "parent": {"database_id": TASKS_DB_ID},
            "properties": {
                "Name": {
                    "title": [
                        {"text": {"content": payload.title}}
                    ]
                }
            }
        }

        notion_resp = requests.post(
            "https://api.notion.com/v1/pages",
            headers=NOTION_HEADERS,
            data=json.dumps(notion_payload)
        )

        if notion_resp.status_code != 200:
            raise HTTPException(
                status_code=notion_resp.status_code,
                detail=notion_resp.text
            )

        notion_data = notion_resp.json()

        # (optional) local DB create
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
        raise HTTPException(status_code=500, detail=f"Failed to create task: {e}")


# ============================================================
# UPDATE
# ============================================================

@router.patch("/{task_id}")
def update_task(task_id: str, updates: TaskUpdate):
    if not tasks_service_global:
        raise HTTPException(500, "TasksService not initialized")

    try:
        task = tasks_service_global.update_task(task_id, updates)
    except ValueError as e:
        raise HTTPException(404, str(e))

    return {"status": "updated", "task": to_resp(task)}


# ============================================================
# GET ALL
# ============================================================

@router.get("/all")
def list_tasks():
    if not tasks_service_global:
        raise HTTPException(500, "TasksService not initialized")

    tasks = tasks_service_global.get_all()
    return [to_resp(t) for t in tasks]


# ============================================================
# DELETE
# ============================================================

@router.delete("/{task_id}")
def delete_task(task_id: str):
    if not tasks_service_global:
        raise HTTPException(500, "TasksService not initialized")

    try:
        deleted = tasks_service_global.delete_task(task_id)
    except ValueError as e:
        raise HTTPException(404, str(e))

    return {"status": "deleted", "task": to_resp(deleted)}