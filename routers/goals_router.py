# routers/goals_router.py
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
@router.patch("/{goal_id}")
async def update_goal(
    goal_id: str,
    data: GoalUpdate,
    goals_service=Depends(get_goals_service)
):
    try:
        logger.info(f"Updating goal with ID: {goal_id}")
        updated = goals_service.update_goal(goal_id, data)
        logger.info(f"Goal with ID: {goal_id} updated successfully.")
        return {"status": "updated", "goal": updated.model_dump()}
    except ValueError as e:
        logger.error(f"Goal with ID: {goal_id} not found for update. Error: {str(e)}")
        raise HTTPException(404, str(e))


# ================================
# LIST ALL GOALS
# ================================
@router.get("/all")
async def list_goals(goals_service=Depends(get_goals_service)):
    logger.info("Fetching all goals.")
    goals = [g.model_dump() for g in goals_service.get_all()]
    logger.info(f"Fetched {len(goals)} goals.")
    return {"goals": goals}


# ================================
# DELETE GOAL
# ================================
@router.delete("/{goal_id}")
async def delete_goal(
    goal_id: str,
    goals_service=Depends(get_goals_service),
    notion=Depends(get_notion_service)
):
    try:
        logger.info(f"Deleting goal with ID: {goal_id}")
        deleted = goals_service.delete_goal(goal_id)

        notion_status = "skip"

        if deleted.notion_id:
            try:
                logger.info(f"Attempting to delete Notion page for goal ID: {goal_id}")
                # Correct method for deleting Notion page
                res = await notion.delete_page(deleted.notion_id)  # Use delete_page for goal deletion
                notion_status = "deleted" if res["ok"] else res["error"]
                logger.info(f"Notion deletion status: {notion_status}")
            except Exception as e:
                notion_status = f"failed: {e}"
                logger.error(f"Failed to delete goal from Notion. Error: {str(e)}")

        return {
            "status": "deleted",
            "goal": deleted.model_dump(),
            "notion": notion_status
        }

    except ValueError as e:
        logger.error(f"Goal with ID: {goal_id} not found for deletion. Error: {str(e)}")
        raise HTTPException(404, str(e))
