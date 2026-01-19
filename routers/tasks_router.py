# routers/tasks_router.py
from __future__ import annotations

import logging
import os
from uuid import UUID, uuid4
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Depends, Request

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel
from services.tasks_service import TasksService
from dependencies import get_tasks_service, get_notion_service

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/tasks", tags=["Tasks"])


# ============================================================
# CANONICAL WRITE GUARDS (match ai_ops_router semantics)
# ============================================================


def _env_true(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() == "true"


def _ops_safe_mode_enabled() -> bool:
    # Hard block writes when enabled
    return _env_true("OPS_SAFE_MODE", "false")


def _ceo_token_enforcement_enabled() -> bool:
    # Token is enforced ONLY when CEO_TOKEN_ENFORCEMENT=true
    return _env_true("CEO_TOKEN_ENFORCEMENT", "false")


def _require_ceo_token_if_enforced(request: Request) -> None:
    """
    Canon: optional CEO-only writes.
    Enforced ONLY when CEO_TOKEN_ENFORCEMENT=true.
    """
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


def _is_ceo_request(request: Request) -> bool:
    """
    Check if the request is from a CEO user.
    CEO users are identified by:
    1. Valid X-CEO-Token header (if CEO_TOKEN_ENFORCEMENT is enabled)
    2. X-Initiator == "ceo_chat" or similar CEO indicators
    """
    # If enforcement is enabled, check for valid token
    if _ceo_token_enforcement_enabled():
        expected = (os.getenv("CEO_APPROVAL_TOKEN", "") or "").strip()
        provided = (request.headers.get("X-CEO-Token") or "").strip()
        if expected and provided == expected:
            return True

    # Check for CEO indicators in request (for non-enforced mode)
    initiator = (request.headers.get("X-Initiator") or "").strip().lower()
    if initiator in ("ceo_chat", "ceo_dashboard", "ceo"):
        return True

    return False


def _guard_write(request: Request) -> None:
    # CEO users bypass OPS_SAFE_MODE restrictions
    if _is_ceo_request(request):
        _require_ceo_token_if_enforced(request)
        return

    # Non-CEO users must pass all checks
    if _ops_safe_mode_enabled():
        raise HTTPException(
            status_code=403,
            detail="OPS_SAFE_MODE enabled (writes blocked)",
        )
    _require_ceo_token_if_enforced(request)


# ============================================================
# HELPERS
# ============================================================


def _task_to_dict(task: TaskModel) -> dict:
    if hasattr(task, "model_dump"):
        return task.model_dump()
    if hasattr(task, "to_dict"):
        return task.to_dict()
    try:
        return dict(task)  # last resort
    except Exception:
        return {"task": str(task)}


# ================================
# CREATE TASK (WRITE via WriteGateway)
# ================================
@router.post("/create", response_model=TaskModel)
async def create_task(
    request: Request,
    payload: TaskCreate,
    tasks_service: TasksService = Depends(get_tasks_service),
    notion=Depends(get_notion_service),
):
    _guard_write(request)

    if not payload.title or not payload.description:
        raise HTTPException(
            status_code=400, detail="Title and description are required."
        )

    logger.info("Creating task with title: %s", payload.title)

    try:
        db_id = os.getenv("NOTION_TASKS_DB_ID")
        if not db_id:
            raise HTTPException(status_code=500, detail="NOTION_TASKS_DB_ID not set")

        payload_dict = (
            payload.model_dump() if hasattr(payload, "model_dump") else dict(payload)
        )

        async def _wg_create_with_notion(env):
            # 1) local domain create (inside commit)
            out = await tasks_service._wg_create_task(env)
            created_task_id = out.get("task_id")
            if not created_task_id:
                raise RuntimeError("Task domain create failed: missing task_id")

            # 2) notion create (inside commit)
            goal_id_str = None
            goal_id_val = payload_dict.get("goal_id")
            if isinstance(goal_id_val, UUID):
                goal_id_str = str(goal_id_val)
            elif goal_id_val:
                goal_id_str = str(goal_id_val)

            notion_payload: Dict[str, Any] = {
                "parent": {"database_id": db_id},
                "properties": {
                    "Name": {
                        "title": [{"text": {"content": payload_dict.get("title")}}]
                    },
                    "Description": {
                        "rich_text": [
                            {"text": {"content": payload_dict.get("description")}}
                        ]
                    },
                },
            }

            if payload_dict.get("deadline"):
                notion_payload["properties"]["Deadline"] = {
                    "date": {"start": payload_dict.get("deadline")}
                }

            if payload_dict.get("priority"):
                notion_payload["properties"]["Priority"] = {
                    "select": {"name": payload_dict.get("priority")}
                }

            if goal_id_str:
                notion_payload["properties"]["Goal"] = {
                    "relation": [{"id": goal_id_str}]
                }
            # DISABLED: direct Notion create_page removed (governed flow only)
            pass
            # 3) attach notion ids locally
            created_task_id_s = str(created_task_id)
            notion_id = None
            notion_url = None
            t = tasks_service.tasks.get(created_task_id_s)
            if t:
                t.notion_id = notion_id
                if hasattr(t, "notion_url"):
                    t.notion_url = notion_url
                t.updated_at = tasks_service._now()

            if hasattr(tasks_service, "_trigger_sync"):
                tasks_service._trigger_sync()

            return {
                "task_id": created_task_id_s,
                "notion_id": notion_id,
                "notion_url": notion_url,
            }

        # Override handler so Notion I/O happens INSIDE WriteGateway commit
        tasks_service.write_gateway.register_handler(
            "tasks_create", _wg_create_with_notion
        )

        envelope = {
            "command": "tasks_create",
            "actor_id": "system",
            "resource": "tasks",
            "payload": {"data": payload_dict},
            "task_id": "TASKS_CREATE",
            "execution_id": f"exec_{uuid4().hex}",
        }

        res = await tasks_service.write_gateway.write(envelope)

        if res.get("success") is True and res.get("status") in ("applied", "replayed"):
            data = res.get("data") or {}
            task_id_val = data.get("task_id")
            if not task_id_val:
                raise HTTPException(
                    500, detail="Write applied but missing task_id in response"
                )

            task_id = str(task_id_val)
            task = tasks_service.tasks.get(task_id)
            if not task:
                raise HTTPException(500, detail="Task created but not found locally")
            return task

        if res.get("status") == "requires_approval":
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": res.get("reason"),
                    "approval_id": res.get("approval_id"),
                    "write_id": res.get("write_id"),
                },
            )

        raise HTTPException(
            status_code=403, detail=res.get("reason") or "write_rejected"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Task creation failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Task creation failed: {e}")


# ================================
# UPDATE TASK (WRITE via WriteGateway)
# ================================
@router.patch("/{task_id}", response_model=TaskModel)
async def update_task(
    request: Request,
    task_id: str,
    payload: TaskUpdate,
    tasks_service: TasksService = Depends(get_tasks_service),
):
    _guard_write(request)

    logger.info("Updating task ID: %s", task_id)
    try:
        # Keep service API as-is; do not assume its expected type
        res = await tasks_service.update_task(task_id, payload)

        if (
            isinstance(res, dict)
            and res.get("success") is True
            and res.get("status") in ("applied", "replayed")
        ):
            updated = tasks_service.tasks.get(task_id)
            if not updated:
                raise HTTPException(
                    status_code=404, detail=f"Task {task_id} not found after update"
                )
            return updated

        if isinstance(res, dict) and res.get("status") == "requires_approval":
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": res.get("reason"),
                    "approval_id": res.get("approval_id"),
                    "write_id": res.get("write_id"),
                },
            )

        # default error
        reason = res.get("reason") if isinstance(res, dict) else None
        raise HTTPException(status_code=400, detail=reason or "update_failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Task update failed (%s): %s", task_id, e)
        raise HTTPException(status_code=400, detail=str(e))


# ================================
# DELETE TASK (WRITE via WriteGateway)
# ================================
@router.delete("/{task_id}")
async def delete_task(
    request: Request,
    task_id: str,
    tasks_service: TasksService = Depends(get_tasks_service),
    notion=Depends(get_notion_service),
):
    _guard_write(request)

    logger.info("Deleting task ID: %s", task_id)

    try:

        async def _wg_delete_with_notion(env):
            # capture notion_id before delete
            t = tasks_service.tasks.get(task_id)
            notion_id = getattr(t, "notion_id", None) if t else None

            out = await tasks_service._wg_delete_task(env)

            if notion_id:
                # DISABLED: direct Notion delete_page removed (governed flow only)
                pass
            return {"deleted": True, "notion_id": notion_id, "domain": out}

        tasks_service.write_gateway.register_handler(
            "tasks_delete", _wg_delete_with_notion
        )

        envelope = {
            "command": "tasks_delete",
            "actor_id": "system",
            "resource": f"task:{task_id}",
            "payload": {"task_id": task_id},
            "task_id": "TASKS_DELETE",
            "execution_id": f"exec_{uuid4().hex}",
        }

        res = await tasks_service.write_gateway.write(envelope)

        if res.get("success") is True and res.get("status") in ("applied", "replayed"):
            return {
                "message": f"Task {task_id} deleted from backend + Notion.",
                "read_only": False,
            }

        if res.get("status") == "requires_approval":
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": res.get("reason"),
                    "approval_id": res.get("approval_id"),
                    "write_id": res.get("write_id"),
                },
            )

        raise HTTPException(
            status_code=404, detail=res.get("reason") or f"Task {task_id} not found."
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Task delete failed (%s): %s", task_id, e)
        raise HTTPException(status_code=500, detail=str(e))


# ================================
# LIST TASKS (READ-ONLY)
# ================================
@router.get("/all")
async def list_tasks(tasks_service: TasksService = Depends(get_tasks_service)):
    try:
        tasks = tasks_service.get_all()
        return {
            "status": "ok",
            "tasks": [_task_to_dict(t) for t in tasks],
            "read_only": True,
        }
    except Exception as e:
        logger.error("Failed to list tasks: %s", e)
        raise HTTPException(status_code=500, detail="Failed to list tasks")


# ============================================================
# FAZA 9 Ä‚ËĂ˘â€šÂ¬Ă˘â‚¬ĹĄ PLAN Ä‚ËĂ˘â‚¬Â Ă˘â‚¬â„˘ TASK Ä‚ËĂ˘â‚¬Â Ă˘â‚¬â„˘ EXECUTION VIEW (READ-ONLY)
# ============================================================
@router.get("/overview")
async def task_execution_overview(
    tasks_service: TasksService = Depends(get_tasks_service),
):
    tasks = tasks_service.get_all()

    overview = []
    for t in tasks:
        d = _task_to_dict(t)
        overview.append(
            {
                "task_id": d.get("id"),
                "title": d.get("title"),
                "goal_id": d.get("goal_id"),
                "status": d.get("status"),
                "priority": d.get("priority"),
                "deadline": d.get("deadline"),
                "notion_url": d.get("notion_url"),
                "execution": {
                    "assigned": bool(d.get("assigned_agent")),
                    "agent_id": d.get("assigned_agent"),
                    "last_error": d.get("last_error"),
                },
            }
        )

    return {
        "tasks": overview,
        "read_only": True,
    }
