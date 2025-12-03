import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Optional, List

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel
from services.notion_service import get_notion_service


class TasksService:
    goals_service = None
    sync_service = None

    def __init__(self):
        self.tasks: Dict[str, TaskModel] = {}

    # ============================================================
    # BIND
    # ============================================================
    def bind_goals_service(self, goals_service):
        self.goals_service = goals_service

    def bind_sync_service(self, sync_service):
        self.sync_service = sync_service

    # ============================================================
    # HELPERS
    # ============================================================
    def _now(self):
        return datetime.now(timezone.utc)

    # ============================================================
    # TO_DICT (EXPORTED TO SYNC)
    # ============================================================
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

    # ============================================================
    # CREATE
    # ============================================================
    async def create_task(self, data: TaskCreate) -> TaskModel:
        now = self._now()
        task_id = uuid4().hex

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

        # Save locally
        self.tasks[task_id] = task

        # Create in Notion
        notion = get_notion_service()
        res = await notion.create_task(task)

        if res["ok"]:
            notion_id = res["data"]["id"]
            task.notion_id = notion_id

        return task

    # ============================================================
    # UPDATE
    # ============================================================
    async def update_task(self, task_id: str, updates: TaskUpdate):
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError("Task not found")

        # Apply local changes
        for field in updates.model_fields:
            val = getattr(updates, field)
            if val is not None:
                setattr(task, field, val)

        task.updated_at = self._now()

        # Push update to Notion
        notion = get_notion_service()
        await notion.update_task(task.notion_id, updates)

        return task

    # ============================================================
    # DELETE
    # ============================================================
    async def delete_task(self, task_id: str):
        task = self.tasks.get(task_id)
        if not task:
            return {"ok": False, "error": "Task not found"}

        # Remove locally
        self.tasks.pop(task_id)

        return {
            "ok": True,
            "notion_id": task.notion_id,
        }

    # ============================================================
    # GET ALL
    # ============================================================
    def get_all_tasks(self) -> List[TaskModel]:
        return list(self.tasks.values())
