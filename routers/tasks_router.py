from fastapi import APIRouter, HTTPException, Depends
import logging

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel

from dependencies import (
    get_tasks_service,
    get_notion_service
)

# Inicijalizujemo logger
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
    logger.info(f"Creating task with title: {payload.title}")
    try:
        task = await tasks_service.create_task(payload)
        
        notion_payload = {
            "parent": {"database_id": os.getenv("NOTION_TASKS_DB_ID")},
            "properties": {
                "Name": {
                    "title": [{"text": {"content": payload.title}}]
                }
            }
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
