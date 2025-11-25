from fastapi import APIRouter, HTTPException, Depends
from typing import Optional, List
from pydantic import BaseModel
import os

from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate

# Injected from main.py
goals_service_global = None
notion_service_global = None

router = APIRouter(prefix="/goals", tags=["Goals"])


# ============================================================
# DEPENDENCIES
# ============================================================

def get_goals_service():
    if goals_service_global is None:
        raise HTTPException(500, "GoalsService not initialized")
    return goals_service_global


def get_notion_service():
    if notion_service_global is None:
        raise HTTPException(500, "NotionService not initialized")
    return notion_service_global


# ============================================================
# RESPONSE MODEL
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


# ============================================================
# CREATE GOAL (ASYNC)
# ============================================================

@router.post("/create")
async def create_goal(
    payload: GoalCreate,
    goals_service=Depends(get_goals_service),
    notion=Depends(get_notion_service)
):
    try:
        notion_payload = {
            "parent": {"database_id": os.getenv("NOTION_GOALS_DB_ID")},
            "properties": {
                "Name": {
                    "title": [{"text": {"content": payload.title}}]
                }
            }
        }

        notion_res = await notion.create_page(notion_payload)

        notion_id = notion_res.get("id")
        notion_url = notion_res.get("url")

        # Local DB create
        goal = goals_service.create_goal(payload)

        return {
            "status": "created",
            "notion_page_id": notion_id,
            "notion_url": notion_url,
            "local_goal": goal.model_dump(),
        }

    except Exception as e:
        raise HTTPException(500, f"Error creating goal: {str(e)}")


# ============================================================
# UPDATE GOAL
# ============================================================

@router.patch("/{goal_id}")
async def update_goal(
    goal_id: str,
    updates: GoalUpdate,
    goals_service=Depends(get_goals_service)
):
    try:
        updated = goals_service.update_goal(goal_id, updates)
        return {"status": "updated", "goal": updated.model_dump()}
    except ValueError as e:
        raise HTTPException(404, str(e))


# ============================================================
# LIST GOALS
# ============================================================

@router.get("/all")
async def get_all(goals_service=Depends(get_goals_service)):
    return {"goals": [g.model_dump() for g in goals_service.get_all()]}


# ============================================================
# DELETE GOAL
# ============================================================

@router.delete("/{goal_id}")
async def delete_goal(goal_id: str, goals_service=Depends(get_goals_service)):
    try:
        deleted = goals_service.delete_goal(goal_id)
        return {"status": "deleted", "goal": deleted.model_dump()}
    except ValueError as e:
        raise HTTPException(404, str(e))
