from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, List

from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate

# Will be injected from main.py
goals_service_global = None

router = APIRouter(prefix="/goals", tags=["Goals"])


# ============================================================
# RESPONSE MODELS
# ============================================================

class GoalResponse(BaseModel):
    id: str
    title: str
    description: Optional[str]
    deadline: Optional[str]
    parent_id: Optional[str]
    priority: Optional[str]
    status: str
    progress: int
    children: List[str]

    class Config:
        from_attributes = True


def to_response(goal):
    return GoalResponse(
        id=goal.id,
        title=goal.title,
        description=goal.description,
        deadline=goal.deadline,
        parent_id=goal.parent_id,
        priority=goal.priority,
        status=goal.status,
        progress=goal.progress,
        children=goal.children,
    )


# ============================================================
# ROUTES
# ============================================================

@router.post("/create")
def create_goal(payload: GoalCreate):
    if goals_service_global is None:
        raise HTTPException(500, "GoalsService not initialized")

    try:
        goal = goals_service_global.create_goal(payload)
    except Exception as e:
        raise HTTPException(400, f"Failed to create goal: {e}")

    return {"status": "created", "goal": to_response(goal)}


@router.patch("/{goal_id}")
def update_goal(goal_id: str, updates: GoalUpdate):
    if goals_service_global is None:
        raise HTTPException(500, "GoalsService not initialized")

    try:
        goal = goals_service_global.update_goal(goal_id, updates)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(400, f"Update failed: {e}")

    return {"status": "updated", "goal": to_response(goal)}


@router.get("/all")
def get_all_goals():
    if goals_service_global is None:
        raise HTTPException(500, "GoalsService not initialized")

    goals = goals_service_global.get_all()

    return {"count": len(goals), "items": [to_response(g) for g in goals]}


@router.delete("/{goal_id}")
def delete_goal(goal_id: str):
    if goals_service_global is None:
        raise HTTPException(500, "GoalsService not initialized")

    try:
        removed = goals_service_global.delete_goal(goal_id)
    except ValueError as e:
        raise HTTPException(404, str(e))

    return {"status": "deleted", "goal": to_response(removed)}