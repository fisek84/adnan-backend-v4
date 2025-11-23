from fastapi import APIRouter, Depends, HTTPException
from services.tasks_service import TasksService
from models.task_create import TaskCreate
from models.task_update import TaskUpdate

router = APIRouter(prefix="/tasks")

# global service instance (injected through main.py)
tasks_service_global: TasksService = None

def get_tasks_service() -> TasksService:
    if tasks_service_global is None:
        raise ValueError("TasksService not initialized")
    return tasks_service_global


# ---------------------------------------------------------
# STATUS
# ---------------------------------------------------------
@router.get("/")
def status():
    return {"message": "Tasks endpoint active"}


# ---------------------------------------------------------
# CREATE TASK
# ---------------------------------------------------------
@router.post("/create")
def create_task(payload: TaskCreate, service: TasksService = Depends(get_tasks_service)):
    return service.create_task(payload)


# ---------------------------------------------------------
# GET ALL TASKS
# ---------------------------------------------------------
@router.get("/all")
def get_all_tasks(service: TasksService = Depends(get_tasks_service)):
    return service.get_all()


# ---------------------------------------------------------
# GET TASK BY ID
# ---------------------------------------------------------
@router.get("/{task_id}")
def get_task(task_id: str, service: TasksService = Depends(get_tasks_service)):
    task = service.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


# ---------------------------------------------------------
# UPDATE TASK
# ---------------------------------------------------------
@router.put("/{task_id}")
def update_task(task_id: str, payload: TaskUpdate, service: TasksService = Depends(get_tasks_service)):
    try:
        return service.update_task(task_id, payload)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------
# DELETE TASK
# ---------------------------------------------------------
@router.delete("/{task_id}")
def delete_task(task_id: str, service: TasksService = Depends(get_tasks_service)):
    try:
        return service.delete_task(task_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------
# ASSIGN TASK TO GOAL
# ---------------------------------------------------------
@router.post("/{task_id}/assign/{goal_id}")
def assign_task(task_id: str, goal_id: str, service: TasksService = Depends(get_tasks_service)):
    try:
        return service.assign_task(task_id, goal_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------
# REORDER TASKS
# ---------------------------------------------------------
@router.post("/reorder")
def reorder_tasks(ordered_ids: list[str], service: TasksService = Depends(get_tasks_service)):
    try:
        return service.reorder_tasks(ordered_ids)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------
# GENERATE TASK FROM GOAL
# ---------------------------------------------------------
@router.post("/generate-from-goal/{goal_id}")
def generate_from_goal(goal_id: str, service: TasksService = Depends(get_tasks_service)):
    if not service.goals_service:
        raise HTTPException(status_code=500, detail="GoalsService not linked")

    goal = service.goals_service.goals.get(goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")

    return service.generate_task_from_goal(goal)