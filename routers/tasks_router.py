from fastapi import APIRouter, HTTPException
from typing import Optional

from models.task_create import TaskCreate
from models.task_update import TaskUpdate

# Will be injected from main.py
tasks_service_global = None

router = APIRouter(prefix="/tasks", tags=["Tasks"])


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
# ROUTES
# ============================================================
@router.post("/create")
def create_task(payload: TaskCreate):
    if not tasks_service_global:
        raise HTTPException(500, "TasksService not initialized")

    task = tasks_service_global.create_task(payload)
    return {
        "status": "created",
        "task": to_resp(task)
    }


@router.patch("/{task_id}")
def update_task(task_id: str, updates: TaskUpdate):
    if not tasks_service_global:
        raise HTTPException(500, "TasksService not initialized")

    try:
        task = tasks_service_global.update_task(task_id, updates)
    except ValueError as e:
        raise HTTPException(404, str(e))

    return {
        "status": "updated",
        "task": to_resp(task)
    }


@router.get("/all")
def list_tasks():
    if not tasks_service_global:
        raise HTTPException(500, "TasksService not initialized")

    tasks = tasks_service_global.get_all()
    return [to_resp(t) for t in tasks]


@router.delete("/{task_id}")
def delete_task(task_id: str):
    if not tasks_service_global:
        raise HTTPException(500, "TasksService not initialized")

    try:
        deleted = tasks_service_global.delete_task(task_id)
    except ValueError as e:
        raise HTTPException(404, str(e))

    return {
        "status": "deleted",
        "task": to_resp(deleted)
    }