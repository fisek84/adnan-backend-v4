from fastapi import APIRouter, HTTPException, Depends
from uuid import uuid4
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
# CREATE GOAL (WRITE via WriteGateway)
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

        async def _wg_create_with_notion(env):
            data = env.payload.get("data") or {}
            notion_db_id = env.payload.get("notion_db_id")

            notion_payload = {
                "parent": {"database_id": notion_db_id},
                "properties": {
                    "Name": {"title": [{"text": {"content": data.get("title")}}]}
                },
            }

            notion_res = await notion.create_page(notion_payload)
            if not notion_res.get("ok"):
                raise RuntimeError("Notion page creation failed")

            notion_id = notion_res["data"]["id"]
            new_goal = goals_service.create_goal(data, notion_id=notion_id)

            if hasattr(goals_service, "_trigger_sync"):
                goals_service._trigger_sync()

            return {
                "local": new_goal.model_dump(),
                "notion_page_id": notion_id,
            }

        # override handler to ensure Notion write happens inside gateway commit
        goals_service.write_gateway.register_handler(
            "goals_create", _wg_create_with_notion
        )

        envelope = {
            "command": "goals_create",
            "actor_id": "system",
            "resource": "goals",
            "payload": {
                "data": payload.model_dump(),
                "notion_db_id": db_id,
            },
            "task_id": "GOALS_CREATE",
            "execution_id": f"exec_{uuid4().hex}",
        }

        res = await goals_service.write_gateway.write(envelope)

        if res.get("success") is True and res.get("status") in ("applied", "replayed"):
            data = res.get("data") or {}
            return {
                "status": "created",
                "local": data.get("local"),
                "notion_page_id": data.get("notion_page_id"),
            }

        if res.get("status") == "requires_approval":
            raise HTTPException(
                409,
                {
                    "reason": res.get("reason"),
                    "approval_id": res.get("approval_id"),
                    "write_id": res.get("write_id"),
                },
            )

        raise HTTPException(403, res.get("reason") or "write_rejected")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Goal creation failed: {e}")
        raise HTTPException(500, f"Goal creation failed: {e}")


# ================================
# UPDATE GOAL (WRITE via GoalsService/WriteGateway)
# ================================
@router.patch("/{goal_id}")
async def update_goal(
    goal_id: str,
    payload: GoalUpdate,
    goals_service=Depends(get_goals_service),
):
    try:
        res = await goals_service.update_goal(goal_id, payload.model_dump())

        if isinstance(res, dict) and res.get("success") is not None:
            if res.get("success") is True and res.get("status") in (
                "applied",
                "replayed",
            ):
                updated_goal: GoalModel = goals_service.goals.get(goal_id)
                if not updated_goal:
                    raise HTTPException(404, "Updated goal not found")
                return updated_goal.model_dump()

            if res.get("status") == "requires_approval":
                raise HTTPException(
                    409,
                    {
                        "reason": res.get("reason"),
                        "approval_id": res.get("approval_id"),
                        "write_id": res.get("write_id"),
                    },
                )

            raise HTTPException(403, res.get("reason") or "write_rejected")

        # fallback legacy behavior
        fallback_goal: GoalModel = goals_service.goals.get(goal_id)
        if not fallback_goal:
            raise HTTPException(404, "Updated goal not found")
        return fallback_goal.model_dump()

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, str(e))


# ================================
# DELETE GOAL (WRITE via WriteGateway)
# ================================
@router.delete("/{goal_id}")
async def delete_goal(
    goal_id: str,
    goals_service=Depends(get_goals_service),
    notion=Depends(get_notion_service),
):
    try:

        async def _wg_delete_with_notion(env):
            notion_id = None

            if hasattr(goals_service, "_wg_delete_goal"):
                out = await goals_service._wg_delete_goal(env)
                notion_id = out.get("notion_id")
            else:
                out = await goals_service.delete_goal(goal_id)
                notion_id = out.get("notion_id")

            if notion_id:
                await notion.delete_page(notion_id)

            return {"notion_id": notion_id, "deleted": True}

        goals_service.write_gateway.register_handler(
            "goals_delete", _wg_delete_with_notion
        )

        envelope = {
            "command": "goals_delete",
            "actor_id": "system",
            "resource": f"goal:{goal_id}",
            "payload": {"goal_id": goal_id},
            "task_id": "GOALS_DELETE",
            "execution_id": f"exec_{uuid4().hex}",
        }

        res = await goals_service.write_gateway.write(envelope)

        if res.get("success") is True and res.get("status") in ("applied", "replayed"):
            return {"status": "deleted", "goal_id": goal_id}

        if res.get("status") == "requires_approval":
            raise HTTPException(
                409,
                {
                    "reason": res.get("reason"),
                    "approval_id": res.get("approval_id"),
                    "write_id": res.get("write_id"),
                },
            )

        raise HTTPException(403, res.get("reason") or "write_rejected")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Goal delete failed: {e}")
        raise HTTPException(500, f"Goal delete failed: {e}")
