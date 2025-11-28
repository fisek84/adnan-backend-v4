from fastapi import APIRouter, HTTPException
from typing import List

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskResponse
from services.tasks_service import (
    create_task,
    update_task,
    delete_task,
    get_all_tasks,
    create_tasks_batch
)

router = APIRouter(tags=["Tasks"])

# ===============================
# GET ALL
# ===============================
@router.get("/tasks/all", response_model=List[TaskResponse])
async def all_tasks():
    return get_all_tasks()


# ===============================
# CREATE SINGLE TASK
# ===============================
@router.post("/tasks/create", response_model=TaskResponse)
async def create_single_task(data: TaskCreate):
    try:
        return create_task(data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===============================
# UPDATE
# ===============================
@router.patch("/tasks/{task_id}")
async def update_single_task(task_id: str, data: TaskUpdate):
    try:
        return update_task(task_id, data)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===============================
# DELETE
# ===============================
@router.delete("/tasks/{task_id}")
async def delete_single_task(task_id: str):
    try:
        return delete_task(task_id)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ===============================
# BATCH CREATE (NOVO)
# ===============================
@router.post("/tasks/batch")
async def create_batch_tasks(payload: List[TaskCreate]):
    """
    Omogućava GPT agentima da kreiraju 10, 50 ili 200 taskova odjednom.
    """
    try:
        created = create_tasks_batch(payload)
        return {
            "count": len(created),
            "items": created
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
