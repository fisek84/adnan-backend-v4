import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict
import logging

from models.task_create import TaskCreate
from models.task_model import TaskModel
from services.notion_service import NotionService

# Inicijalizacija loggera
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

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
    # CREATE TASK
    # ------------------------------------------------------------
    async def create_task(self, data: TaskCreate) -> TaskModel:
        now = self._now()
        task_id = uuid4().hex

        # Provjera da li je goals_service inicijaliziran
        if not self.goals_service:
            logger.error("Goals service is not initialized. Please bind goals service before using.")
            raise ValueError("Goals service is not initialized. Please bind goals service before using.")

        # Ako goal_id nije validan UUID, konvertiraj ga
        if data.goal_id:
            try:
                data.goal_id = str(data.goal_id)  # Osiguraj da goal_id bude string
                logger.info(f"Using existing goal_id: {data.goal_id}")
            except Exception as e:
                logger.error(f"Error converting goal_id: {e}")
                raise ValueError("Invalid goal_id format.")
        else:
            logger.info("No goal_id provided, creating a new goal.")
            try:
                new_goal = await self.goals_service.create_goal({
                    'title': data.title,
                    'priority': data.priority,
                    'deadline': data.deadline
                })
                data.goal_id = new_goal.id  # Postavi novo kreirani goal_id kao string
                logger.info(f"Created new goal with ID: {data.goal_id}")
            except Exception as e:
                logger.error(f"Error creating new goal: {e}")
                raise ValueError("Error creating new goal.")

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

        # Povezivanje sa Notion-om
        try:
            res = await self.notion.create_task(task)
        except Exception as e:
            logger.error(f"Error connecting to Notion: {e}")
            raise ValueError("Failed to create task in Notion.")
        
        if isinstance(res, str):
            res = {"ok": False, "error": res}
        if not isinstance(res, dict):
            res = {"ok": False, "error": "Invalid Notion response"}

        res.setdefault("ok", False)
        res.setdefault("data", {})

        if res["ok"] and "id" in res["data"]:
            task.notion_id = res["data"]["id"]

        self._trigger_sync()  # Sinhronizacija sa Notion-om
        return task
