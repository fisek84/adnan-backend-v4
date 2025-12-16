from fastapi import APIRouter, HTTPException, Depends
import os
import logging

from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate
from models.base_model import GoalModel
from dependencies import get_goals_service, get_notion_service

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/goals", tags=["Goals"])


# ================================
# GET ALL GOALS
# ================================
@router.get("/all")
async def get_all_goals(goals_service=Depends(get_goals_service)):
    try:
        goals = goals_service.get_all()
        return {"status": "ok", "goals": [g.model_dump() for g in goals]}
    except Exception as e:
        logger.error(f"Failed to list goals: {e}")
        raise HTTPException(500, f"Failed to list goals: {e}")


# ================================
# CREATE GOAL  ✅ ISPRAVLJENO
# POST /goals
# ================================
@router.post("")
async def create_goal(
    payload: GoalCreate,
    goals_service=Depends(get_goals_service),
    notion=Depends(get_notion_service),
):
    try:
        db_id = os.getenv("NOTION_GOALS_DB_ID")
        if not db_id:
            raise HTTPException(500, "NOTION_GOALS_DB_ID not set")

        notion_payload = {
            "parent": {"database_id": db_id},
            "properties": {
                "Name": {
                    "title": [{"text": {"content": payload.title}}]
                }
            },
        }

        notion_res = await notion.create_page(notion_payload)
        if not notion_res.get("ok"):
            raise HTTPException(500, "Notion page creation failed")

        notion_id = notion_res["data"]["id"]

        new_goal = goals_service.create_goal(payload, notion_id=notion_id)

        return {
            "status": "created",
            "local": new_goal.model_dump(),
            "notion_page_id": notion_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Goal creation failed: {e}")
        raise HTTPException(500, f"Goal creation failed: {e}")


# ================================
# UPDATE GOAL
# ================================
@router.patch("/{goal_id}")
async def update_goal(
    goal_id: str,
    payload: GoalUpdate,
    goals_service=Depends(get_goals_service),
):
    try:
        await goals_service.update_goal(goal_id, payload)

        updated_goal: GoalModel = goals_service.goals.get(goal_id)
        if not updated_goal:
            raise HTTPException(404, "Updated goal not found")

        return updated_goal.model_dump()

    except Exception as e:
        raise HTTPException(400, str(e))


# ================================
# DELETE GOAL
# ================================
@router.delete("/{goal_id}")
async def delete_goal(
    goal_id: str,
    goals_service=Depends(get_goals_service),
    notion=Depends(get_notion_service),
):
    result = await goals_service.delete_goal(goal_id)
    notion_id = result.get("notion_id")

    if notion_id:
        await notion.delete_page(notion_id)

    return {"status": "deleted", "goal_id": goal_id}
