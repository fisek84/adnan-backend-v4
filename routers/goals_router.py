from fastapi import APIRouter, HTTPException, Depends
import os

from pydantic import BaseModel
from typing import List, Optional

from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate

from main import get_goals_service, get_notion_service

router = APIRouter(prefix="/goals", tags=["Goals"])


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
# CREATE GOAL
# ============================================================

@router.post("/create")
async def create_goal(
    payload: GoalCreate,
    goals_service=Depends(get_goals_service),
    notion=Depends(get_notion_service)
):
    try:
        db_id = os.getenv("NOTION_GOALS_DB_ID")

        notion_payload = {
            "parent": {"database_id": db_id},
            "properties": {
                "Name": {
                    "title": [{"text": {"content": payload.title}}]
                }
            }
        }

        notion_res = await notion.create_page(notion_payload)

        local_goal = goals_service.create_goal(payload)

        return {
            "status": "created",
            "local": local_goal.model_dump(),
            "notion_page_id": notion_res.get("id"),
            "notion_url": notion_res.get("url")
        }

    except Exception as e:
        raise HTTPException(500, f"Goal creation failed: {str(e)}")


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
