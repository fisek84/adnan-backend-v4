# routers/goals_router.py
#
# CANONICAL PATCH (FAZA 4)
#
# Cilj:
# - READ path ostaje otvoren (GET)
# - WRITE path je strogo guarded:
#   - OPS_SAFE_MODE => hard block (403)
#   - CEO_TOKEN_ENFORCEMENT => optional token gate (X-CEO-Token)
# - Nema “chat implicit write” ovdje, ali ovo je direktna write-surface pa mora imati guard.
#
# Napomena:
# - Ovaj router i dalje koristi WriteGateway/GoalsService approval mehaniku (409 requires_approval),
#   ali dodatno štitimo rute od “slučajnog” write-a kada je OPS_SAFE_MODE uključen.
# - Happy path testovi koriste /api/execute i /api/ai-ops/approval/approve — ovaj router ne smije
#   lomiti taj tok.

from __future__ import annotations

import os
import logging
from uuid import uuid4
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate
from models.base_model import GoalModel
from dependencies import get_goals_service, get_notion_service

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/goals", tags=["Goals"])


# ------------------------------------------------------------
# CANONICAL WRITE GUARDS (shared semantics with ai_ops_router)
# ------------------------------------------------------------


def _env_true(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() == "true"


def _ops_safe_mode_enabled() -> bool:
    return _env_true("OPS_SAFE_MODE", "false")


def _ceo_token_enforcement_enabled() -> bool:
    return _env_true("CEO_TOKEN_ENFORCEMENT", "false")


def _require_ceo_token_if_enforced(request: Request) -> None:
    if not _ceo_token_enforcement_enabled():
        return

    expected = os.getenv("CEO_APPROVAL_TOKEN", "").strip()
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="CEO token enforcement enabled but CEO_APPROVAL_TOKEN is not set",
        )

    provided = (request.headers.get("X-CEO-Token") or "").strip()
    if provided != expected:
        raise HTTPException(status_code=403, detail="CEO token required")


def _guard_write(request: Request) -> None:
    if _ops_safe_mode_enabled():
        raise HTTPException(
            status_code=403, detail="OPS_SAFE_MODE enabled (writes blocked)"
        )
    _require_ceo_token_if_enforced(request)


# ================================
# GET ALL GOALS (READ-ONLY)
# ================================
@router.get("/all")
async def get_all_goals(goals_service=Depends(get_goals_service)) -> Dict[str, Any]:
    try:
        goals = goals_service.get_all()
        return {"status": "ok", "read_only": True, "goals": [g.model_dump() for g in goals]}
    except Exception as e:  # noqa: BLE001
        logger.error("Failed to list goals: %s", e)
        raise HTTPException(500, f"Failed to list goals: {e}") from e


# ================================
# CREATE GOAL (WRITE via WriteGateway)
# ================================
@router.post("")
async def create_goal(
    request: Request,
    payload: GoalCreate,
    goals_service=Depends(get_goals_service),
    notion=Depends(get_notion_service),
) -> Dict[str, Any]:
    _guard_write(request)

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
        goals_service.write_gateway.register_handler("goals_create", _wg_create_with_notion)

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
                "read_only": False,
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
    except Exception as e:  # noqa: BLE001
        logger.error("Goal creation failed: %s", e)
        raise HTTPException(500, f"Goal creation failed: {e}") from e


# ================================
# UPDATE GOAL (WRITE via GoalsService/WriteGateway)
# ================================
@router.patch("/{goal_id}")
async def update_goal(
    request: Request,
    goal_id: str,
    payload: GoalUpdate,
    goals_service=Depends(get_goals_service),
) -> Any:
    _guard_write(request)

    try:
        res = await goals_service.update_goal(goal_id, payload.model_dump())

        if isinstance(res, dict) and res.get("success") is not None:
            if res.get("success") is True and res.get("status") in ("applied", "replayed"):
                updated_goal: Optional[GoalModel] = goals_service.goals.get(goal_id)
                if not updated_goal:
                    raise HTTPException(404, "Updated goal not found")
                out = updated_goal.model_dump()
                if isinstance(out, dict):
                    out.setdefault("read_only", False)
                return out

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

        # legacy fallback behavior
        fallback_goal: Optional[GoalModel] = goals_service.goals.get(goal_id)
        if not fallback_goal:
            raise HTTPException(404, "Updated goal not found")
        out = fallback_goal.model_dump()
        if isinstance(out, dict):
            out.setdefault("read_only", False)
        return out

    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, str(e)) from e


# ================================
# DELETE GOAL (WRITE via WriteGateway)
# ================================
@router.delete("/{goal_id}")
async def delete_goal(
    request: Request,
    goal_id: str,
    goals_service=Depends(get_goals_service),
    notion=Depends(get_notion_service),
) -> Dict[str, Any]:
    _guard_write(request)

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

        goals_service.write_gateway.register_handler("goals_delete", _wg_delete_with_notion)

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
            return {"status": "deleted", "read_only": False, "goal_id": goal_id}

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
    except Exception as e:  # noqa: BLE001
        logger.error("Goal delete failed: %s", e)
        raise HTTPException(500, f"Goal delete failed: {e}") from e
