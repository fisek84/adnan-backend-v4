from fastapi import APIRouter, Depends, HTTPException
from typing import List
import logging

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel

from services.tasks_service import TasksService
from dependencies import get_tasks_service, get_notion_service

router = APIRouter(prefix="/tasks", tags=["Tasks"])
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# =======================================================
# GET ALL TASKS
# =======================================================
@router.get("/all", response_model=List[TaskModel])
async def get_all_tasks(tasks_service: TasksService = Depends(get_tasks_service)):
    logger.info("Fetching all tasks...")
    tasks = tasks_service.get_all_tasks()  # Pozivamo metod za dobijanje svih zadataka
    logger.info(f"Fetched {len(tasks)} tasks.")
    return tasks


# =======================================================
# CREATE TASK
# =======================================================
@router.post("/create", response_model=TaskModel)
async def create_task(
    payload: TaskCreate,
    tasks_service: TasksService = Depends(get_tasks_service)
):
    logger.info(f"Creating task: {payload.title}")
    try:
        task = await tasks_service.create_task(payload)  # Pozivamo metod za kreiranje zadatka
        return task
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        raise HTTPException(status_code=500, detail="Error creating task.")


# =======================================================
# UPDATE TASK
# =======================================================
@router.patch("/{task_id}", response_model=TaskModel)
async def update_task(
    task_id: str,
    payload: TaskUpdate,
    tasks_service: TasksService = Depends(get_tasks_service)
):
    logger.info(f"Updating task ID: {task_id}")
    try:
        updated = await tasks_service.update_task(task_id, payload)  # Pozivamo metod za ažuriranje zadatka
        return updated
    except Exception as e:
        logger.error(f"Task update failed ({task_id}): {e}")
        raise HTTPException(400, str(e))


# =======================================================
# DELETE TASK
# =======================================================
@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    tasks_service: TasksService = Depends(get_tasks_service),
    notion=Depends(get_notion_service)
):
    logger.info(f"Deleting task ID: {task_id}")

    result = await tasks_service.delete_task(task_id)  # Pozivamo metod za brisanje zadatka

    if not result["ok"]:
        raise HTTPException(404, f"Task {task_id} not found.")

    notion_id = result.get("notion_id")
    if notion_id:
        logger.info(f"Deleting Notion page: {notion_id}")
        notion_res = await notion._safe_request(
            "DELETE",
            f"https://api.notion.com/v1/pages/{notion_id}"
        )

        if notion_res["ok"]:
            logger.info(f"Deleted from Notion: {notion_id}")
            return {"message": f"Task {task_id} deleted from backend + Notion."}
        else:
            logger.warning(f"Task deleted locally, but Notion delete failed.")
            return {
                "warning": "Task removed locally, but Notion deletion failed.",
                "notion_error": notion_res["error"]
            }

    logger.info(f"Task deleted locally only: {task_id}")
    return {"message": f"Task {task_id} deleted locally (no Notion page)."}
