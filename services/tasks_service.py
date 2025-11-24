from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel


class TasksService:
    """
    Evolia TasksService v4.1 (Notion-Safe Version)

    - Temporary UUIDs replaced with Notion IDs during sync_up
    - Full Goal↔Task bindings
    - Works with async NotionSyncService
    """

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
    # INTERNAL: trigger debounce sync (FINAL ASYNC PATCH)
    # ============================================================
    def _trigger_sync(self):
        if not self.sync_service:
            return

        import asyncio

        try:
            loop = asyncio.get_event_loop()

            # Ako event loop već radi (FastAPI + Uvicorn + Render)
            if loop.is_running():
                loop.create_task(self.sync_service.debounce_tasks_sync())
            else:
                # Lokalno bez running loop-a
                loop.run_until_complete(self.sync_service.debounce_tasks_sync())

        except RuntimeError:
            # Fallback — kreiraj privremeni loop
            try:
                asyncio.run(self.sync_service.debounce_tasks_sync())
            except Exception:
                pass

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
            status=data.status or "pending",
            order=data.order or 0,
            created_at=now,
            updated_at=now,
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

        for field in [
            "title", "description", "deadline", "goal_id",
            "priority", "status", "order"
        ]:
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
    # SYNC FROM NOTION (DOWN)
    # ============================================================
    def sync_from_notion(self, data: Dict[str, Any]) -> TaskModel:
        task_id = data["id"]
        existing = self.tasks.get(task_id)

        goal_rel = data.get("goal")
        goal_id = goal_rel[0] if goal_rel else None

        if existing:
            return self.update_task(task_id, TaskUpdate(
                title=data.get("name"),
                description=data.get("description"),
                deadline=data.get("due_date"),
                goal_id=goal_id,
                priority=data.get("priority"),
                status=data.get("status"),
                order=data.get("order"),
            ))

        return self.create_task(TaskCreate(
            title=data.get("name"),
            description=data.get("description"),
            deadline=data.get("due_date"),
            goal_id=goal_id,
            priority=data.get("priority"),
            status=data.get("status"),
            order=data.get("order"),
        ), forced_id=task_id)

    # ============================================================
    # UTILITIES
    # ============================================================
    def get_all(self):
        return list(self.tasks.values())

    def _to_dict(self, task: TaskModel) -> Dict[str, Any]:
        return {
            "id": task.id,
            "name": task.title,
            "description": task.description,
            "due_date": task.deadline,
            "goal": [task.goal_id] if task.goal_id else [],
            "priority": task.priority,
            "status": task.status,
            "order": task.order,
        }