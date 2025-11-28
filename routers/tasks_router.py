from fastapi import APIRouter, Depends
from typing import List

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel

from services.tasks_service import TasksService
from dependencies import get_tasks_service

router = APIRouter(prefix="/tasks", tags=["Tasks"])


# =====================================================
# GET ALL
# =====================================================
@router.get("/all", response_model=List[TaskModel])
async def all_tasks(tasks_service: TasksService = Depends(get_tasks_service)):
    return await tasks_service.get_all_tasks()


# =====================================================
# CREATE SINGLE
# =====================================================
@router.post("/create", response_model=TaskModel)
async def create_task_endpoint(
    payload: TaskCreate,
    tasks_service: TasksService = Depends(get_tasks_service)
):
    return await tasks_service.create_task(payload)


# =====================================================
# BATCH CREATE
# =====================================================
@router.post("/batch")
async def batch_create_endpoint(
    payload: List[TaskCreate],
    tasks_service: TasksService = Depends(get_tasks_service)
):
    items = await tasks_service.create_tasks_batch(payload)
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
    return await tasks_service.update_task(task_id, payload)


# =====================================================
# DELETE
# =====================================================
@router.delete("/{task_id}")
async def delete_task_endpoint(
    task_id: str,
    tasks_service: TasksService = Depends(get_tasks_service)
):
    return await tasks_service.delete_task(task_id)