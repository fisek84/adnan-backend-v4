from fastapi import APIRouter, HTTPException, Depends
import os
import logging

from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate
from models.base_model import GoalModel

from dependencies import get_goals_service, get_notion_service

router = APIRouter(prefix="/goals", tags=["Goals"])

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


# ===============================================================
# CREATE GOAL
# ===============================================================
@router.post("/create", response_model=dict)
async def create_goal(
    payload: GoalCreate,
    goals_service=Depends(get_goals_service),
    notion=Depends(get_notion_service)
):
    try:
        logger.info(f"[GOALS] Creating goal: {payload.title}")

        db_id = os.getenv("NOTION_GOALS_DB_ID")
        if not db_id:
            raise HTTPException(500, "NOTION_GOALS_DB_ID missing in environment")

        # -----------------------------
        # 1. CREATE IN NOTION
        # -----------------------------
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
            logger.error(f"[GOALS] Notion error: {notion_res['error']}")
            raise HTTPException(500, f"Notion error: {notion_res['error']}")

        notion_id = notion_res["data"]["id"]
        notion_url = notion_res["data"].get("url")

        # -----------------------------
        # 2. CREATE LOCAL GOAL
        # -----------------------------
        new_goal = goals_service.create_goal(
            payload,
            notion_id=notion_id
        )

        logger.info(f"[GOALS] Created successfully: {new_goal.id}")

        return {
            "status": "created",
            "local": new_goal.model_dump(),
            "notion_page_id": notion_id,
            "notion_url": notion_url
        }

    except Exception as e:
        logger.error(f"[GOALS] Goal creation failed: {e}")
        raise HTTPException(500, f"Goal creation failed: {e}")


# ===============================================================
# UPDATE GOAL
# ===============================================================
@router.patch("/{goal_id}", response_model=dict)
async def update_goal(
    goal_id: str,
    payload: GoalUpdate,
    goals_service=Depends(get_goals_service),
):
    try:
        logger.info(f"[GOALS] Updating: {goal_id}")

        updated = goals_service.update_goal(goal_id, payload)

        return {
            "status": "updated",
            "goal": updated.model_dump()
        }

    except ValueError as e:
        logger.error(f"[GOALS] Update error: {e}")
        raise HTTPException(404, str(e))


# ===============================================================
# LIST GOALS
# ===============================================================
@router.get("/all", response_model=dict)
async def list_goals(goals_service=Depends(get_goals_service)):
    logger.info("[GOALS] Fetching all goals")

    goals = [g.model_dump() for g in goals_service.get_all()]

    return {"goals": goals}


# ===============================================================
# DELETE GOAL
# ===============================================================
@router.delete("/{goal_id}", response_model=dict)
async def delete_goal(
    goal_id: str,
    goals_service=Depends(get_goals_service),
    notion=Depends(get_notion_service)
):
    try:
        logger.info(f"[GOALS] Deleting: {goal_id}")

        deleted = goals_service.delete_goal(goal_id)
        notion_status = "skipped"

        # -------------------------------------------------------
        # SAFELY DELETE FROM NOTION — only if you have delete API
        # -------------------------------------------------------
        if deleted.notion_id:
            try:
                logger.info(f"[GOALS] Deleting Notion page: {deleted.notion_id}")

                # You MUST add this to your NotionService for real deletion:
                res = await notion.delete_page(deleted.notion_id)

                notion_status = "deleted" if res["ok"] else res["error"]

            except Exception as e:
                notion_status = f"failed: {e}"
                logger.error(f"[GOALS] Notion delete error: {e}")

        return {
            "status": "deleted",
            "goal": deleted.model_dump(),
            "notion": notion_status
        }

    except ValueError as e:
        logger.error(f"[GOALS] Delete error: {e}")
        raise HTTPException(404, str(e))
