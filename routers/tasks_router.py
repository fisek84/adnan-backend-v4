from fastapi import APIRouter, HTTPException, Depends
import logging
import os
from uuid import UUID, uuid4

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel
from services.tasks_service import TasksService

from dependencies import get_tasks_service, get_notion_service

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

router = APIRouter(prefix="/tasks", tags=["Tasks"])


def _task_to_dict(task: TaskModel) -> dict:
    if hasattr(task, "model_dump"):
        return task.model_dump()
    if hasattr(task, "to_dict"):
        return task.to_dict()
    return dict(task)  # last resort


# ================================
# CREATE TASK (WRITE via WriteGateway)
# ================================
@router.post("/create", response_model=TaskModel)
async def create_task(
    payload: TaskCreate,
    tasks_service: TasksService = Depends(get_tasks_service),
    notion=Depends(get_notion_service),
):
    if not payload.title or not payload.description:
        raise HTTPException(
            status_code=400, detail="Title and description are required."
        )

    logger.info(f"Creating task with title: {payload.title}")

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

            # 2) notion create (inside commit)
            goal_id_str = None
            goal_id_val = payload_dict.get("goal_id")
            if isinstance(goal_id_val, UUID):
                goal_id_str = str(goal_id_val)
            elif goal_id_val:
                goal_id_str = str(goal_id_val)

            notion_payload = {
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

            notion_res = await notion.create_page(notion_payload)
            if not notion_res.get("ok"):
                raise RuntimeError(
                    f"Notion page creation failed: {notion_res.get('error')}"
                )

            notion_id = notion_res["data"]["id"]
            notion_url = notion_res["data"].get("url")

            # 3) attach notion ids locally
            t = tasks_service.tasks.get(created_task_id)
            if t:
                t.notion_id = notion_id
                if hasattr(t, "notion_url"):
                    t.notion_url = notion_url
                t.updated_at = tasks_service._now()

            tasks_service._trigger_sync()

            return {
                "task_id": created_task_id,
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
            if task_id_val is None:
                raise HTTPException(
                    500, "Write applied but missing task_id in response"
                )

            task_id = str(task_id_val)  # normalize for dict key
            task = tasks_service.tasks.get(task_id)
            if not task:
                raise HTTPException(500, "Task created but not found locally")
            return task

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
        logger.error(f"Task creation failed: {e}")
        raise HTTPException(500, f"Task creation failed: {e}")


# ================================
# UPDATE TASK (WRITE via WriteGateway)
# ================================
@router.patch("/{task_id}", response_model=TaskModel)
async def update_task(
    task_id: str,
    payload: TaskUpdate,
    tasks_service: TasksService = Depends(get_tasks_service),
):
    logger.info(f"Updating task ID: {task_id}")
    try:
        res = await tasks_service.update_task(task_id, payload)

        if res.get("success") is True and res.get("status") in ("applied", "replayed"):
            updated = tasks_service.tasks.get(task_id)
            if not updated:
                raise HTTPException(404, f"Task {task_id} not found after update")
            return updated

        if res.get("status") == "requires_approval":
            raise HTTPException(
                409,
                {
                    "reason": res.get("reason"),
                    "approval_id": res.get("approval_id"),
                    "write_id": res.get("write_id"),
                },
            )

        raise HTTPException(400, res.get("reason") or "update_failed")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Task update failed ({task_id}): {e}")
        raise HTTPException(400, str(e))


# ================================
# DELETE TASK (WRITE via WriteGateway)
# ================================
@router.delete("/{task_id}")
async def delete_task(
    task_id: str,
    tasks_service: TasksService = Depends(get_tasks_service),
    notion=Depends(get_notion_service),
):
    logger.info(f"Deleting task ID: {task_id}")

    try:

        async def _wg_delete_with_notion(env):
            # capture notion_id before delete
            t = tasks_service.tasks.get(task_id)
            notion_id = getattr(t, "notion_id", None) if t else None

            out = await tasks_service._wg_delete_task(env)

            if notion_id:
                notion_res = await notion.delete_page(notion_id)
                if not notion_res.get("ok"):
                    raise RuntimeError(
                        f"Notion deletion failed: {notion_res.get('error')}"
                    )

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
            return {"message": f"Task {task_id} deleted from backend + Notion."}

        if res.get("status") == "requires_approval":
            raise HTTPException(
                409,
                {
                    "reason": res.get("reason"),
                    "approval_id": res.get("approval_id"),
                    "write_id": res.get("write_id"),
                },
            )

        raise HTTPException(404, res.get("reason") or f"Task {task_id} not found.")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Task delete failed ({task_id}): {e}")
        raise HTTPException(500, str(e))


# ================================
# LIST TASKS
# ================================
@router.get("/all")
async def list_tasks(tasks_service: TasksService = Depends(get_tasks_service)):
    try:
        tasks = tasks_service.get_all()
        return {"status": "ok", "tasks": [_task_to_dict(t) for t in tasks]}
    except Exception as e:
        logger.error(f"Failed to list tasks: {e}")
        raise HTTPException(500, "Failed to list tasks")


# ============================================================
# FAZA 9 — PLAN → TASK → EXECUTION VIEW (READ-ONLY)
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
