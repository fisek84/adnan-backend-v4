from fastapi import APIRouter, HTTPException, Depends
import logging
from models.task_create import TaskCreate
from models.task_model import TaskModel
from dependencies import get_tasks_service

router = APIRouter(prefix="/tasks", tags=["Tasks"])

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ===============================================================
# CREATE TASK
# ===============================================================
@router.post("/create", response_model=dict)
async def create_task(
    payload: TaskCreate,
    tasks_service=Depends(get_tasks_service)
):
    try:
        logger.info(f"[TASKS] Creating task: {payload.title}")
        new_task = await tasks_service.create_task(payload)

        return {
            "status": "created",
            "task": new_task.model_dump()  # Pretpostavljamo da `model_dump` vrati JSON format
        }

    except Exception as e:
        logger.error(f"[TASKS] Task creation failed: {e}")
        raise HTTPException(500, f"Task creation failed: {e}")


# ===============================================================
# UPDATE TASK
# ===============================================================
@router.patch("/{task_id}", response_model=dict)
async def update_task(
    task_id: str,
    payload: dict,  # Možeš koristiti specifični model kao TaskUpdate, ako želiš
    tasks_service=Depends(get_tasks_service)
):
    try:
        logger.info(f"[TASKS] Updating task: {task_id}")

        # Poziv metode za ažuriranje zadatka
        updated_task = tasks_service.update_task(task_id, payload)

        return {
            "status": "updated",
            "task": updated_task.model_dump()  # Pretpostavljamo da `model_dump` vrati JSON format
        }

    except ValueError as e:
        logger.error(f"[TASKS] Update error: {e}")
        raise HTTPException(404, str(e))

