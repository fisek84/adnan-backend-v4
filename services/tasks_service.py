import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.base_model import TaskModel


class TasksService:
    goals_service = None
    sync_service = None

    def __init__(self):
        self.tasks: Dict[str, TaskModel] = {}

    # ============================================================
    # BINDING
    # ============================================================
    def bind_goals_service(self, goals_service):
        self.goals_service = goals_service

    def bind_sync_service(self, sync_service):
        self.sync_service = sync_service

    # ============================================================
    # SAFE ASYNC TRIGGER (FIXED)
    # ============================================================
    def _trigger_sync(self):
        if not self.sync_service:
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.sync_service.debounce_tasks_sync())
        except RuntimeError:
            asyncio.get_event_loop().create_task(self.sync_service.debounce_tasks_sync())

    # ============================================================
    # HELPERS
    # ============================================================
    def _now(self):
        return datetime.now(timezone.utc)

    # ============================================================
    # CREATE TASK
    # ============================================================
    def create_task(self, data: TaskCreate, forced_id: Optional[str] = None) -> TaskModel:
        now = self._now()
        task_id = forced_id or uuid4().hex

        new_task = TaskModel(
            id=task_id,
            title=data.title,
            description=data.description,
            deadline=data.deadline,
            goal_id=data.goal_id,
            priority=data.priority,
            status="pending",
            order=0,
            created_at=now,
            updated_at=now,
            notion_id=None
        )

        self.tasks[task_id] = new_task
        self._trigger_sync()
        return new_task

    # ============================================================
    # UPDATE TASK
    # ============================================================
    def update_task(self, task_id: str, updates: TaskUpdate) -> TaskModel:
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        for field in ["title", "description", "deadline", "goal_id", "priority", "status", "order"]:
            val = getattr(updates, field, None)
            if val is not None:
                setattr(task, field, val)

        task.updated_at = self._now()
        self._trigger_sync()
        return task

    # ============================================================
    # DELETE TASK
    # ============================================================
    def delete_task(self, task_id: str) -> TaskModel:
        task = self.tasks.pop(task_id, None)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        self._trigger_sync()
        return task

    # ============================================================
    # SYNC FROM NOTION
    # ============================================================
    def sync_from_notion(self, data: Dict[str, Any]) -> TaskModel:
        task_id = data["id"]
        existing = self.tasks.get(task_id)

        goal_rel = data.get("goal")
        goal_id = goal_rel[0] if goal_rel else None

        if existing:
            existing.notion_id = task_id
            return self.update_task(task_id, TaskUpdate(
                title=data.get("name"),
                description=data.get("description"),
                deadline=data.get("due_date"),
                goal_id=goal_id,
                priority=data.get("priority"),
                status=data.get("status"),
                order=data.get("order"),
            ))

        new_task = self.create_task(
            TaskCreate(
                title=data.get("name"),
                description=data.get("description"),
                deadline=data.get("due_date"),
                goal_id=goal_id,
                priority=data.get("priority"),
            ),
            forced_id=task_id
        )

        new_task.notion_id = task_id
        return new_task

    # ============================================================
    # UTILITIES
    # ============================================================
    def get_all(self):
        return list(self.tasks.values())

    def _to_dict(self, task: TaskModel) -> Dict[str, Any]:
        return {
            "id": task.id,
            "notion_id": task.notion_id,
            "name": task.title,
            "description": task.description,
            "due_date": task.deadline,
            "goal": [task.goal_id] if task.goal_id else [],
            "priority": task.priority,
            "status": task.status,
            "order": task.order,
        }