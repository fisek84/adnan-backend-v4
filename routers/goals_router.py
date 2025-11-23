from fastapi import APIRouter, Depends, HTTPException, status
from services.goals_service import GoalsService
from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate

router = APIRouter(prefix="/goals", tags=["Goals"])

# Global DI reference (postavlja se iz main.py)
goals_service_global: GoalsService | None = None


# ============================================================
# INTERNAL VALIDATION (Centralized)
# ============================================================
def _require_goals_service() -> GoalsService:
    if goals_service_global is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="GoalsService is not initialized"
        )
    return goals_service_global


# ============================================================
# STATUS
# ============================================================
@router.get(
    "/",
    summary="Check Goals API status",
    status_code=200
)
def goals_status():
    return {"status": "ok", "message": "Goals endpoint active"}


# ============================================================
# GET ALL GOALS
# ============================================================
@router.get(
    "/all",
    summary="Retrieve all goals",
    status_code=200
)
def get_all_goals(service: GoalsService = Depends(_require_goals_service)):
    return {
        "status": "success",
        "count": len(service.goals),
        "items": service.get_all()
    }


# ============================================================
# CREATE GOAL
# ============================================================
@router.post(
    "/create",
    summary="Create a new goal",
    status_code=status.HTTP_201_CREATED
)
def create_goal(payload: GoalCreate, service: GoalsService = Depends(_require_goals_service)):
    goal = service.create_goal(payload)
    return {
        "status": "success",
        "message": "Goal created",
        "goal_id": goal.id,
        "data": goal
    }


# ============================================================
# GET GOAL BY ID
# ============================================================
@router.get(
    "/{goal_id}",
    summary="Get a goal by ID",
    status_code=200
)
def get_goal(goal_id: str, service: GoalsService = Depends(_require_goals_service)):
    goal = service.goals.get(goal_id)
    if not goal:
        raise HTTPException(status_code=404, detail="Goal not found")
    return {"status": "success", "data": goal}


# ============================================================
# UPDATE GOAL
# ============================================================
@router.put(
    "/{goal_id}",
    summary="Update goal fields",
    status_code=200
)
def update_goal(goal_id: str, payload: GoalUpdate, service: GoalsService = Depends(_require_goals_service)):
    try:
        updated = service.update_goal(goal_id, payload)
        return {
            "status": "success",
            "message": "Goal updated",
            "data": updated
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ============================================================
# DELETE GOAL
# ============================================================
@router.delete(
    "/{goal_id}",
    summary="Delete a goal by ID",
    status_code=200
)
def delete_goal(goal_id: str, service: GoalsService = Depends(_require_goals_service)):
    try:
        removed = service.delete_goal(goal_id)
        return {
            "status": "success",
            "message": "Goal deleted",
            "deleted_id": removed.id
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))