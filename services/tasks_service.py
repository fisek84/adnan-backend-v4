import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, List
import logging

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel
from services.notion_service import NotionService

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

class TasksService:
    goals_service = None
    sync_service = None

    def __init__(self, notion_service: NotionService):
        self.tasks: Dict[str, TaskModel] = {}
        self.notion = notion_service

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
        logger.info("Starting task creation...")
        now = self._now()
        task_id = uuid4().hex

        if not self.goals_service:
            logger.error("Goals service is not initialized.")
            raise ValueError("Goals service is not initialized.")

        if not data.title:
            logger.error("Title is required to create a task.")
            raise ValueError("Title is required to create a task.")

        # --------------------------------------------------------
        # FIX: Resolve LOCAL goal_id -> NOTION goal_id
        # --------------------------------------------------------
        notion_goal_id = None

        if data.goal_id:
            try:
                local_goal_id = str(data.goal_id)
                goal = self.goals_service.goals.get(local_goal_id)

                if goal and goal.notion_id:
                    notion_goal_id = goal.notion_id
                    logger.info(f"Resolved Notion goal_id: {notion_goal_id}")
                else:
                    logger.warning("Goal exists locally but has no notion_id. Task will be created without relation.")

                data.goal_id = local_goal_id

            except Exception:
                raise ValueError("Invalid goal_id format.")
        else:
            logger.info("Task has no goal relation.")

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

        # --------------------------------------------------------
        # SEND NOTION PAYLOAD WITH PROPER notion_goal_id
        # --------------------------------------------------------
        try:
            res = await self.notion.create_task(task, notion_goal_id=notion_goal_id)
        except Exception:
            raise ValueError("Failed to create task in Notion.")

        if isinstance(res, dict) and res.get("ok") and "id" in res.get("data", {}):
            task.notion_id = res["data"]["id"]

        self._trigger_sync()
        return task

    # ------------------------------------------------------------
    # GET ALL TASKS
    # ------------------------------------------------------------
    def get_all_tasks(self) -> List[TaskModel]:
        logger.info(f"[TASKS] Total tasks in service: {len(self.tasks)}")
        return list(self.tasks.values())

    # ------------------------------------------------------------
    # UPDATE TASK
    # ------------------------------------------------------------
    def update_task(self, task_id: str, data: dict) -> TaskModel:
        if task_id not in self.tasks:
            raise ValueError(f"Task with id {task_id} not found")

        task = self.tasks[task_id]

        task.title = data.get('title', task.title)
        task.description = data.get('description', task.description)
        task.deadline = data.get('deadline', task.deadline)
        task.priority = data.get('priority', task.priority)
        task.status = data.get('status', task.status)

        task.updated_at = self._now()
        return task

    # ------------------------------------------------------------
    # UPDATE MODEL VERSION
    # ------------------------------------------------------------
    async def update_task_model(self, task_id: str, data: TaskUpdate) -> TaskModel:
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
        return task

    # ------------------------------------------------------------
    # DELETE TASK
    # ------------------------------------------------------------
    async def delete_task(self, task_id: str) -> dict:
        if task_id not in self.tasks:
            raise ValueError(f"Task with id {task_id} not found")

        task = self.tasks.pop(task_id)
        return {"ok": True, "task": task}
