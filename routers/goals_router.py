from fastapi import APIRouter, HTTPException, Depends
import os

from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate

from dependencies import (
    get_goals_service,
    get_notion_service
)

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
            return {"status": "notion_error", "detail": notion_res["error"]}

        notion_id = notion_res["data"]["id"]
        notion_url = notion_res["data"]["url"]

        new_goal = goals_service.create_goal(
            payload,
            notion_id=notion_id
        )

        return {
            "status": "created",
            "local": new_goal.model_dump(),
            "notion_page_id": notion_id,
            "notion_url": notion_url
        }

    except Exception as e:
        raise HTTPException(500, f"Goal creation failed: {e}")


# ================================
# UPDATE
# ================================
@router.patch("/{goal_id}")
async def update_goal(
    goal_id: str,
    data: GoalUpdate,
    goals_service=Depends(get_goals_service)
):
    try:
        updated = goals_service.update_goal(goal_id, data)
        return {"status": "updated", "goal": updated.model_dump()}
    except ValueError as e:
        raise HTTPException(404, str(e))


# ================================
# LIST
# ================================
@router.get("/all")
async def list_goals(goals_service=Depends(get_goals_service)):
    return {"goals": [g.model_dump() for g in goals_service.get_all()]}


# ================================
# DELETE (WITH NOTION ARCHIVE)
# ================================
@router.delete("/{goal_id}")
async def delete_goal(
    goal_id: str,
    goals_service=Depends(get_goals_service),
    notion=Depends(get_notion_service)
):
    try:
        deleted = goals_service.delete_goal(goal_id)

        notion_status = "skip"

        if deleted.notion_id:
            try:
                res = await notion.delete_page(deleted.notion_id)
                notion_status = "archived" if res["ok"] else res["error"]
            except Exception as e:
                notion_status = f"failed: {e}"

        return {
            "status": "deleted",
            "goal": deleted.model_dump(),
            "notion": notion_status
        }

    except ValueError as e:
        raise HTTPException(404, str(e))
