from fastapi import APIRouter
from typing import List

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel

from services.tasks_service import (
    create_task,
    update_task,
    delete_task,
    get_all_tasks,
    create_tasks_batch
)

router = APIRouter(prefix="/tasks", tags=["Tasks"])


# =====================================================
# GET ALL
# =====================================================
@router.get("/all", response_model=List[TaskModel])
async def all_tasks():
    return await get_all_tasks()


# =====================================================
# CREATE SINGLE
# =====================================================
@router.post("/create", response_model=TaskModel)
async def create_task_endpoint(payload: TaskCreate):
    return await create_task(payload)


# =====================================================
# BATCH CREATE
# =====================================================
@router.post("/batch")
async def batch_create_endpoint(payload: List[TaskCreate]):
    items = await create_tasks_batch(payload)
    return {"count": len(items), "items": items}


# =====================================================
# UPDATE
# =====================================================
@router.patch("/{task_id}")
async def update_task_endpoint(task_id: str, payload: TaskUpdate):
    return await update_task(task_id, payload)


# =====================================================
# DELETE
# =====================================================
@router.delete("/{task_id}")
async def delete_task_endpoint(task_id: str):
    return await delete_task(task_id)