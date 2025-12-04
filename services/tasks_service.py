import asyncio
from uuid import uuid4, UUID
from datetime import datetime, timezone
from typing import Dict, Optional, List

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel
from services.notion_service import NotionService


class TasksService:
    goals_service = None
    sync_service = None

    def __init__(self, notion_service: NotionService):
        self.tasks: Dict[str, TaskModel] = {}
        self.notion = notion_service  # NotionService injection

    # ------------------------------------------------------------
    # BINDINGS
    # ------------------------------------------------------------
    def bind_goals_service(self, goals_service):
        self.goals_service = goals_service

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
    # TO_DICT
    # ------------------------------------------------------------
    def to_dict(self, task: TaskModel) -> dict:
        return {
            "id": task.id,
            "notion_id": task.notion_id,
            "title": task.title,
            "description": task.description,
            "goal_id": task.goal_id,
            "deadline": task.deadline,
            "priority": task.priority,
            "status": task.status,
            "order": task.order,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }

    # ------------------------------------------------------------
    # CREATE TASK
    # ------------------------------------------------------------
    async def create_task(self, data: TaskCreate) -> TaskModel:
        now = self._now()
        task_id = uuid4().hex

        # Provjera da li je goals_service inicijaliziran
        if not self.goals_service:
            raise ValueError("Goals service is not initialized. Please bind goals service before using.")

        # Ako goal_id nije validan UUID, konvertiraj ga
        if data.goal_id:
