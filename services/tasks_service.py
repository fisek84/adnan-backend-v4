import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
import logging

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel

from services.write_gateway.write_gateway import WriteGateway, WriteEnvelope

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class TasksService:
    """
    DOMAIN TASK SERVICE — KANONSKI

    Pravila:
    - ne zna Notion
    - ne zna agente
    - ne poziva direktno vanjske API-je
    - proizvodi NAMJERU + lokalnu domensku promjenu,
      a sync servis rješava I/O sloj (npr. Notion)
    """

    sync_service = None

    def __init__(self, write_gateway: Optional[WriteGateway] = None):
        self.tasks: Dict[str, TaskModel] = {}
        self.write_gateway = write_gateway or WriteGateway()

        # SSOT enforcement handlers
        self.write_gateway.register_handler("tasks_create", self._wg_create_task)
        self.write_gateway.register_handler("tasks_update", self._wg_update_task)
        self.write_gateway.register_handler("tasks_delete", self._wg_delete_task)

    # ------------------------------------------------------------
    # BINDINGS
    # ------------------------------------------------------------

    def bind_sync_service(self, sync_service):
        self.sync_service = sync_service

    # ------------------------------------------------------------
    # HELPERS
    # ------------------------------------------------------------

    def _now(self):
        return datetime.now(timezone.utc)

    def _trigger_sync(self):
        if not self.sync_service:
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.sync_service.debounce_tasks_sync())
        except RuntimeError:
            asyncio.get_event_loop().create_task(self.sync_service.debounce_tasks_sync())

    def _wg_execution_id(self, payload: dict) -> str:
        exec_id = payload.get("execution_id") or payload.get("idempotency_key")
        if isinstance(exec_id, str) and exec_id.strip():
            return exec_id.strip()
        return f"exec_{uuid4().hex}"

    # ------------------------------------------------------------
    # CREATE TASK (WRITE via gateway)
    # ------------------------------------------------------------

    async def create_task(self, data: TaskCreate) -> Dict[str, Any]:
        payload = data.model_dump() if hasattr(data, "model_dump") else dict(data)
        envelope = {
            "command": "tasks_create",
            "actor_id": str(payload.get("actor_id") or "system"),
            "resource": "tasks",
            "payload": {"data": payload},
            "task_id": "TASKS_CREATE",
            "execution_id": self._wg_execution_id(payload),
            "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
            "approval_id": payload.get("approval_id"),
        }
        return await self.write_gateway.write(envelope)

    # ------------------------------------------------------------
    # READ
    # ------------------------------------------------------------

    def get_all(self) -> List[TaskModel]:
        return list(self.tasks.values())

    # ------------------------------------------------------------
    # UPDATE (WRITE via gateway)
    # ------------------------------------------------------------

    async def update_task(self, task_id: str, data: TaskUpdate) -> Dict[str, Any]:
        payload = data.model_dump() if hasattr(data, "model_dump") else dict(data)
        envelope = {
            "command": "tasks_update",
            "actor_id": str(payload.get("actor_id") or "system"),
            "resource": f"task:{task_id}",
            "payload": {"task_id": task_id, "data": payload},
            "task_id": "TASKS_UPDATE",
            "execution_id": self._wg_execution_id(payload),
            "metadata": payload.get("metadata") if isinstance(payload.get("metadata"), dict) else None,
            "approval_id": payload.get("approval_id"),
        }
        return await self.write_gateway.write(envelope)

    # ------------------------------------------------------------
    # DELETE (WRITE via gateway)
    # ------------------------------------------------------------

    async def delete_task(self, task_id: str) -> Dict[str, Any]:
        envelope = {
            "command": "tasks_delete",
            "actor_id": "system",
            "resource": f"task:{task_id}",
            "payload": {"task_id": task_id},
            "task_id": "TASKS_DELETE",
            "execution_id": f"exec_{uuid4().hex}",
        }
        return await self.write_gateway.write(envelope)

    # ------------------------------------------------------------
    # WRITE GATEWAY HANDLERS (REAL DOMAIN SIDE EFFECTS)
    # ------------------------------------------------------------

    async def _wg_create_task(self, env: WriteEnvelope) -> Dict[str, Any]:
        payload = env.payload or {}
        data = payload.get("data") or {}

        logger.info("Creating task (domain only)...")

        title = data.get("title")
        if not title:
            raise ValueError("Task title is required.")

        task_id = uuid4().hex
        now = self._now()

        task = TaskModel(
            id=task_id,
            notion_id=None,
            title=title,
            description=data.get("description"),
            goal_id=data.get("goal_id"),
            deadline=data.get("deadline"),
            priority=data.get("priority"),
            status=data.get("status") or "pending",
            order=0,
            created_at=now,
            updated_at=now,
        )

        self.tasks[task_id] = task
        self._trigger_sync()

        return {
            "intent": "create_task",
            "entity": "task",
            "task_id": task_id,
            "payload": task.to_dict(),
        }

    async def _wg_update_task(self, env: WriteEnvelope) -> Dict[str, Any]:
        payload = env.payload or {}
        task_id = str(payload.get("task_id") or "").strip()
        data = payload.get("data") or {}

        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")

        task = self.tasks[task_id]

        if data.get("title") is not None:
            task.title = data.get("title")
        if data.get("description") is not None:
            task.description = data.get("description")
        if data.get("deadline") is not None:
            task.deadline = data.get("deadline")
        if data.get("priority") is not None:
            task.priority = data.get("priority")
        if data.get("status") is not None:
            task.status = data.get("status")

        task.updated_at = self._now()
        self._trigger_sync()

        return {
            "intent": "update_task",
            "entity": "task",
            "task_id": task_id,
            "payload": task.to_dict(),
        }

    async def _wg_delete_task(self, env: WriteEnvelope) -> Dict[str, Any]:
        payload = env.payload or {}
        task_id = str(payload.get("task_id") or "").strip()

        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")

        self.tasks.pop(task_id)
        self._trigger_sync()

        return {
            "intent": "delete_task",
            "entity": "task",
            "task_id": task_id,
            "payload": {"id": task_id},
        }
