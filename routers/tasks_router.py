from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Any

from services.tasks_service import TasksService
from models.task_create import TaskCreate
from models.task_update import TaskUpdate

router = APIRouter(prefix="/tasks", tags=["Tasks"])

# Global service instance (injected through main.py)
tasks_service_global: TasksService = None


# ============================================================
# DEPENDENCY INJECTION
# ============================================================
def get_tasks_service() -> TasksService:
    if tasks_service_global is None:
        raise RuntimeError("TasksService not initialized")
    return tasks_service_global


# ============================================================
# HEALTH CHECK
# ============================================================
@router.get("/", summary="Tasks service status")
def status_check():
    return {"status": "ok", "service": "tasks_router"}


# ============================================================
# CREATE TASK
# ============================================================
@router.post(
    "/create",
    status_code=status.HTTP_201_CREATED,
    summary="Create new task"
)
def create_task(
    payload: TaskCreate,
    service: TasksService = Depends(get_tasks_service)
):
    """
    Creates a new task using validated TaskCreate schema.
    """
    try:
        task = service.create_task(payload)
        return {"status": "success", "task": task}
    except Exception as e:
        raise HTTPException(500, detail=f"Task creation failed: {e}")


# ============================================================
# GET ALL TASKS
# ============================================================
@router.get(
    "/all",
    response_model=List[Any],
    summary="Get all tasks"
)
def get_all_tasks(service: TasksService = Depends(get_tasks_service)):
    return service.get_all()


# ============================================================
# GET TASK BY ID
# ============================================================
@router.get(
    "/{task_id}",
    summary="Get task by ID"
)
def get_task(
    task_id: str,
    service: TasksService = Depends(get_tasks_service)
):
    task = service.tasks.get(task_id)
    if not task:
        raise HTTPException(404, detail="Task not found")
    return task


# ============================================================
# UPDATE TASK
# ============================================================
@router.put(
    "/{task_id}",
    summary="Update task fields"
)
def update_task(
    task_id: str,
    payload: TaskUpdate,
    service: TasksService = Depends(get_tasks_service)
):
    try:
        updated = service.update_task(task_id, payload)
        return {"status": "updated", "task": updated}
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=f"Task update failed: {e}")


# ============================================================
# DELETE TASK
# ============================================================
@router.delete(
    "/{task_id}",
    summary="Delete task"
)
def delete_task(
    task_id: str,
    service: TasksService = Depends(get_tasks_service)
):
    try:
        removed = service.delete_task(task_id)
        return {"status": "deleted", "task": removed}
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=f"Task deletion failed: {e}")


# ============================================================
# ASSIGN TASK TO GOAL
# ============================================================
@router.post(
    "/{task_id}/assign/{goal_id}",
    summary="Assign an existing task to a goal"
)
def assign_task(
    task_id: str,
    goal_id: str,
    service: TasksService = Depends(get_tasks_service)
):
    try:
        assigned = service.assign_task(task_id, goal_id)
        return {"status": "assigned", "task": assigned}
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=f"Task assignment failed: {e}")


# ============================================================
# REORDER TASKS
# ============================================================
@router.post(
    "/reorder",
    summary="Reorder tasks by list of IDs"
)
def reorder_tasks(
    ordered_ids: List[str],
    service: TasksService = Depends(get_tasks_service)
):
    """
    Reorders tasks in memory; ensures stable deterministic ordering.
    """
    try:
        reordered = service.reorder_tasks(ordered_ids)
        return {"status": "reordered", "order": ordered_ids}
    except ValueError as e:
        raise HTTPException(404, detail=str(e))
    except Exception as e:
        raise HTTPException(500, detail=f"Reorder failed: {e}")


# ============================================================
# GENERATE TASK FROM GOAL
# ============================================================
@router.post(
    "/generate-from-goal/{goal_id}",
    summary="Generate a task automatically from an existing goal"
)
def generate_from_goal(
    goal_id: str,
    service: TasksService = Depends(get_tasks_service)
):
    if not service.goals_service:
        raise HTTPException(500, detail="GoalsService not linked")

    goal = service.goals_service.goals.get(goal_id)
    if not goal:
        raise HTTPException(404, detail="Goal not found")

    try:
        new_task = service.generate_task_from_goal(goal)
        return {"status": "generated", "task": new_task}
    except Exception as e:
        raise HTTPException(500, detail=f"Task generation failed: {e}")