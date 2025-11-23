from fastapi import APIRouter, Depends, HTTPException
from services.goals_service import GoalsService
from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate

router = APIRouter(prefix="/goals")

# global DI placeholder
goals_service_global: GoalsService = None

def get_goals_service() -> GoalsService:
    if goals_service_global is None:
        raise HTTPException(status_code=500, detail="GoalsService not initialized")
    return goals_service_global


# ---------------------------------------------------------
# STATUS
# ---------------------------------------------------------
@router.get("/")
def status():
    return {"message": "Goals endpoint active"}


# ---------------------------------------------------------
# GET ALL GOALS  (MORA BITI IZNAD get/{id})
# ---------------------------------------------------------
@router.get("/all")
def get_all_goals(service: GoalsService = Depends(get_goals_service)):
    return service.get_all()


# ---------------------------------------------------------
# CREATE GOAL
# ---------------------------------------------------------
@router.post("/create")
def create_goal(payload: GoalCreate, service: GoalsService = Depends(get_goals_service)):
    return service.create_goal(payload)


# ---------------------------------------------------------
# GET GOAL BY ID
# ---------------------------------------------------------
@router.get("/{goal_id}")
def get_goal(goal_id: str, service: GoalsService = Depends(get_goals_service)):
    goal = service.goals.get(goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    return goal


# ---------------------------------------------------------
# UPDATE GOAL
# ---------------------------------------------------------
@router.put("/{goal_id}")
def update_goal(goal_id: str, payload: GoalUpdate, service: GoalsService = Depends(get_goals_service)):
    try:
        return service.update_goal(goal_id, payload)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ---------------------------------------------------------
# DELETE GOAL
# ---------------------------------------------------------
@router.delete("/{goal_id}")
def delete_goal(goal_id: str, service: GoalsService = Depends(get_goals_service)):
    try:
        return service.delete_goal(goal_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))