import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, List
import logging

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel

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

    def __init__(self):
        self.tasks: Dict[str, TaskModel] = {}

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
            asyncio.get_event_loop().create_task(
                self.sync_service.debounce_tasks_sync()
            )

    # ------------------------------------------------------------
    # CREATE TASK (DOMAIN)
    # ------------------------------------------------------------

    def create_task(self, data: TaskCreate) -> Dict[str, any]:
        """
        Kreira Task domenski objekat i vraća NAMJERU za execution.
        """
        logger.info("Creating task (domain only)...")

        if not data.title:
            raise ValueError("Task title is required.")

        task_id = uuid4().hex
        now = self._now()

        task = TaskModel(
            id=task_id,
            notion_id=None,
            title=data.title,
            description=data.description,
            goal_id=data.goal_id,
            deadline=data.deadline,
            priority=data.priority,
            status=data.status or "pending",
            order=0,
            created_at=now,
            updated_at=now,
        )

        self.tasks[task_id] = task
        self._trigger_sync()

        # 👉 KLJUČNO: vraćamo NAMJERU, ne izvršenje
        return {
            "intent": "create_task",
            "entity": "task",
            "task_id": task_id,
            "payload": task.to_dict(),
        }

    # ------------------------------------------------------------
    # READ
    # ------------------------------------------------------------

    def get_all(self) -> List[TaskModel]:
        return list(self.tasks.values())

    # ------------------------------------------------------------
    # UPDATE (DOMAIN)
    # ------------------------------------------------------------

    def update_task(self, task_id: str, data: TaskUpdate) -> Dict[str, any]:
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")

        task = self.tasks[task_id]

        if data.title is not None:
            task.title = data.title
        if data.description is not None:
            task.description = data.description
        if data.deadline is not None:
            task.deadline = data.deadline
        if data.priority is not None:
            task.priority = data.priority
        if data.status is not None:
            task.status = data.status

        task.updated_at = self._now()
        self._trigger_sync()

        return {
            "intent": "update_task",
            "entity": "task",
            "task_id": task_id,
            "payload": task.to_dict(),
        }

    # ------------------------------------------------------------
    # DELETE (DOMAIN)
    # ------------------------------------------------------------

    def delete_task(self, task_id: str) -> Dict[str, any]:
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")

        task = self.tasks.pop(task_id)
        self._trigger_sync()

        return {
            "intent": "delete_task",
            "entity": "task",
            "task_id": task_id,
            "payload": {"id": task_id},
        }
