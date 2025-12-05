from fastapi import APIRouter, HTTPException, Depends
import os
import logging  # Dodajemo logovanje

from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate

from dependencies import (
    get_goals_service,
    get_notion_service
)

# Inicijalizujemo logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/goals", tags=["Goals"])

# ================================
# CREATE GOAL
# ================================
@router.post("/create")
async def create_goal(
    payload: GoalCreate,
    goals_service=Depends(get_goals_service),
    notion=Depends(get_notion_service)
):
    try:
        logger.info(f"Creating goal with title: {payload.title}")
        
        db_id = os.getenv("NOTION_GOALS_DB_ID")
        if not db_id:
            logger.error("NOTION_GOALS_DB_ID is not set in environment variables.")
            raise HTTPException(500, "NOTION_GOALS_DB_ID is not set.")

        notion_payload = {
            "parent": {"database_id": db_id},
            "properties": {
                "Name": {
                    "title": [{"text": {"content": payload.title}}]
                }
            }
        }

        notion_res = await notion.create_page(notion_payload)

        if not notion_res["ok"]:
            logger.error(f"Notion error: {notion_res['error']}")
            return {"status": "notion_error", "detail": notion_res["error"]}

        notion_id = notion_res["data"]["id"]
        notion_url = notion_res["data"]["url"]

        new_goal = goals_service.create_goal(
            payload,
            notion_id=notion_id
        )

        logger.info(f"Goal created successfully with ID: {notion_id}")

        return {
            "status": "created",
            "local": new_goal.model_dump(),
            "notion_page_id": notion_id,
            "notion_url": notion_url
        }

    except Exception as e:
        logger.error(f"Goal creation failed: {e}")
        raise HTTPException(500, f"Goal creation failed: {e}")

# ================================
# UPDATE GOAL
# ================================
@router.patch("/{goal_id}", response_model=GoalUpdate)
async def update_goal(
    goal_id: str,
    payload: GoalUpdate,
    goals_service=Depends(get_goals_service)
):
    logger.info(f"Updating goal ID: {goal_id}")
    try:
        updated = await goals_service.update_goal(goal_id, payload)
        return updated
    except Exception as e:
        logger.error(f"Goal update failed ({goal_id}): {e}")
        raise HTTPException(400, str(e))

# ================================
# DELETE GOAL
# ================================
@router.delete("/{goal_id}")
async def delete_goal(
    goal_id: str,
    goals_service=Depends(get_goals_service),
    notion=Depends(get_notion_service)
):
    logger.info(f"Deleting goal ID: {goal_id}")

    result = await goals_service.delete_goal(goal_id)

    if not result["ok"]:
        raise HTTPException(404, f"Goal {goal_id} not found.")

    notion_id = result.get("notion_id")
    if notion_id:
        logger.info(f"Deleting Notion page: {notion_id}")
        notion_res = await notion._safe_request(
            "DELETE",
            f"https://api.notion.com/v1/pages/{notion_id}"
        )

        if notion_res["ok"]:
            logger.info(f"Deleted from Notion: {notion_id}")
            return {"message": f"Goal {goal_id} deleted from backend + Notion."}
        else:
            logger.warning(f"Goal deleted locally, but Notion delete failed.")
            return {
                "warning": "Goal removed locally, but Notion deletion failed.",
                "notion_error": notion_res["error"]
            }

    logger.info(f"Goal deleted locally only: {goal_id}")
    return {"message": f"Goal {goal_id} deleted locally (no Notion page)."}
