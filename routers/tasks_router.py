from fastapi import APIRouter, Depends
from typing import List
import logging  # Dodajemo logovanje

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel

from services.tasks_service import TasksService
from dependencies import get_tasks_service
from dependencies import get_notion_service  # Importuj get_notion_service

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/tasks", tags=["Tasks"])

# =====================================================
# GET ALL
# =====================================================
@router.get("/all", response_model=List[TaskModel])
async def all_tasks(tasks_service: TasksService = Depends(get_tasks_service)):
    logger.info("Fetching all tasks.")
    tasks = await tasks_service.get_all_tasks()
    logger.info(f"Fetched {len(tasks)} tasks.")
    return tasks


# =====================================================
# CREATE SINGLE
# =====================================================
@router.post("/create", response_model=TaskModel)
async def create_task_endpoint(
    payload: TaskCreate,
    tasks_service: TasksService = Depends(get_tasks_service)
):
    logger.info(f"Creating task with title: {payload.title}")
    task = await tasks_service.create_task(payload)
    logger.info(f"Task created with ID: {task.id}")
    return task


# =====================================================
# BATCH CREATE
# =====================================================
@router.post("/batch")
async def batch_create_endpoint(
    payload: List[TaskCreate],
    tasks_service: TasksService = Depends(get_tasks_service)
):
    logger.info(f"Creating batch of {len(payload)} tasks.")
    items = await tasks_service.create_tasks_batch(payload)
    logger.info(f"Batch created with {len(items)} tasks.")
    return {"count": len(items), "items": items}


# =====================================================
# UPDATE
# =====================================================
@router.patch("/{task_id}")
async def update_task_endpoint(
    task_id: str,
    payload: TaskUpdate,
    tasks_service: TasksService = Depends(get_tasks_service)
):
    logger.info(f"Updating task with ID: {task_id}")
    result = await tasks_service.update_task(task_id, payload)
    logger.info(f"Task with ID: {task_id} updated.")
    return result


# =====================================================
# DELETE
# =====================================================
@router.delete("/{task_id}")
async def delete_task_endpoint(
    task_id: str,
    tasks_service: TasksService = Depends(get_tasks_service),
    notion=Depends(get_notion_service)  # Dodajemo get_notion_service kao zavisnost
):
    logger.info(f"Deleting task with ID: {task_id}")
    
    # Call the delete_task function from TasksService which is calling NotionService
    result = await tasks_service.delete_task(task_id)

    if result["ok"]:
        # If task is deleted from the service, now delete from Notion
        if result.get("notion_id"):
            logger.info(f"Deleting task with Notion ID: {result['notion_id']}")
            notion_res = await notion.delete_page(result["notion_id"])  # Use delete_page for task deletion
            if notion_res["ok"]:
                logger.info(f"Task {task_id} successfully deleted from Notion and Backend.")
                return {"message": f"Task {task_id} successfully deleted from Notion and Backend."}
            else:
                logger.error(f"Failed to delete task {task_id} from Notion. Error: {notion_res['error']}")
                return {"error": f"Failed to delete task {task_id} from Notion. Error: {notion_res['error']}"}
        else:
            logger.warning(f"Task {task_id} not found in Notion, deleted only from Backend.")
            return {"message": f"Task {task_id} successfully deleted from Backend, but not found in Notion."}
    else:
        logger.error(f"Failed to delete task {task_id}. Error: {result['error']}")
        return {"error": f"Failed to delete task {task_id}. Error: {result['error']}"}
