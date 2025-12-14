from fastapi import APIRouter, HTTPException, Depends
import logging
import os
from uuid import UUID

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel
from services.tasks_service import TasksService

from dependencies import (
    get_tasks_service,
    get_notion_service
)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/tasks", tags=["Tasks"])


# ================================
# CREATE TASK
# ================================
@router.post("/create", response_model=TaskModel)
async def create_task(
    payload: TaskCreate,
    tasks_service=Depends(get_tasks_service),
    notion=Depends(get_notion_service)
):
    if not payload.title or not payload.description:
        raise HTTPException(status_code=400, detail="Title and description are required.")

    logger.info(f"Creating task with title: {payload.title}")

    try:
        task = await tasks_service.create_task(payload)

        goal_id_str = str(payload.goal_id) if isinstance(payload.goal_id, UUID) else payload.goal_id

        notion_payload = {
            "parent": {"database_id": os.getenv("NOTION_TASKS_DB_ID")},
            "properties": {
                "Name": {"title": [{"text": {"content": payload.title}}]},
                "Description": {
                    "rich_text": [{"text": {"content": payload.description}}]
                },
            }
        }

        if payload.deadline:
            notion_payload["properties"]["Deadline"] = {
                "date": {"start": payload.deadline}
            }

        if payload.priority:
            notion_payload["properties"]["Priority"] = {
                "select": {"name": payload.priority}
            }

        if goal_id_str:
            notion_payload["properties"]["Goal"] = {
                "relation": [{"id": goal_id_str}]
            }

        notion_res = await notion.create_page(notion_payload)

        if notion_res["ok"]:
            task.notion_id = notion_res["data"]["id"]
            task.notion_url = notion_res["data"]["url"]
            logger.info(f"Task created successfully in Notion with ID: {task.notion_id}")
        else:
            logger.warning(f"Task created locally but failed in Notion: {notion_res['error']}")

        return task

    except Exception as e:
        logger.error(f"Task creation failed: {e}")
        raise HTTPException(500, f"Task creation failed: {e}")


# ================================
# UPDATE TASK
# ================================
@router.patch("/{task_id}", response_model=TaskModel)
async def update_task(
    task_id: str,
    payload: TaskUpdate,
    tasks_service: TasksService = Depends(get_tasks_service)
):
    logger.info(f"Updating task ID: {task_id}")
    try:
        updated = await tasks_service.update_task(task_id, payload)
        return updated
    except Exception as e:
        logger.error(f"Task update failed ({task_id}): {e}")
        raise HTTPException(400, str(e))


# ================================
# DELETE TASK
# ================================
@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    tasks_service: TasksService = Depends(get_tasks_service),
    notion=Depends(get_notion_service)
):
    logger.info(f"Deleting task ID: {task_id}")

    result = await tasks_service.delete_task(task_id)

    if not result["ok"]:
        raise HTTPException(404, f"Task {task_id} not found.")

    notion_id = result.get("notion_id")

    if notion_id:
        logger.info(f"Deleting Notion page: {notion_id}")
        notion_res = await notion.delete_page(notion_id)

        if notion_res["ok"]:
            return {"message": f"Task {task_id} deleted from backend + Notion."}
        else:
            return {
                "warning": "Task removed locally, but Notion deletion failed.",
                "notion_error": notion_res["error"]
            }

    return {"message": f"Task {task_id} deleted locally (no Notion page)."}


# ================================
# LIST TASKS
# ================================
@router.get("/all")
async def list_tasks(tasks_service=Depends(get_tasks_service)):
    try:
        return tasks_service.get_all_tasks()
    except Exception as e:
        logger.error(f"Failed to list tasks: {e}")
        raise HTTPException(500, "Failed to list tasks")


# ============================================================
# FAZA 9 — PLAN → TASK → EXECUTION VIEW (READ-ONLY)
# ============================================================

@router.get("/overview")
async def task_execution_overview(tasks_service=Depends(get_tasks_service)):
    """
    State-driven task execution snapshot.
    UI / OPS safe.
    """

    tasks = tasks_service.get_all_tasks()

    overview = []
    for t in tasks:
        overview.append({
            "task_id": t.get("id"),
            "title": t.get("title"),
            "goal_id": t.get("goal_id"),
            "status": t.get("status"),
            "priority": t.get("priority"),
            "deadline": t.get("deadline"),
            "notion_url": t.get("notion_url"),
            "execution": {
                "assigned": bool(t.get("assigned_agent")),
                "agent_id": t.get("assigned_agent"),
                "last_error": t.get("last_error"),
            },
        })

    return {
        "tasks": overview,
        "read_only": True,
    }
