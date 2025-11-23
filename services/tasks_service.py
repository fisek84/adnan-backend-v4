from uuid import uuid4
from datetime import datetime
from typing import Dict, Any, Optional

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel


class TasksService:
    """
    Centralni servis za upravljanje Task objektima.
    Kompatibilan sa:
    - GoalsService (auto progress update)
    - NotionSyncService (sync up/down + debounce)
    """

    goals_service = None
    sync_service = None

    def __init__(self):
        self.tasks: dict[str, TaskModel] = {}

    # ---------------------------------------------------------
    # BIND SERVICES
    # ---------------------------------------------------------
    def bind_goals_service(self, goals_service):
        self.goals_service = goals_service

    def bind_sync_service(self, sync_service):
        self.sync_service = sync_service

    # ---------------------------------------------------------
    # INTERNAL: SAFE SYNC TRIGGER
    # ---------------------------------------------------------
    def _trigger_sync(self):
        if not self.sync_service:
            return

        import asyncio

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.sync_service.debounce_tasks_sync())
        except RuntimeError:
            # Ako nema aktivne event petlje (npr. tokom testova)
            pass

    # ---------------------------------------------------------
    # CREATE TASK
    # ---------------------------------------------------------
    def create_task(self, data: TaskCreate, forced_id: Optional[str] = None) -> TaskModel:
        now = datetime.utcnow()
        task_id = forced_id or uuid4().hex

        task = TaskModel(
            id=task_id,
            title=data.title,
            description=data.description,
            goal_id=data.goal_id,
            deadline=data.deadline,
            priority=data.priority,
            status="pending",
            created_at=now,
            updated_at=now,
        )

        self.tasks[task_id] = task

        if self.goals_service and data.goal_id:
            self.goals_service.sync_goal_progress_from_tasks(data.goal_id)

        self._trigger_sync()
        return task

    # ---------------------------------------------------------
    # UPDATE TASK
    # ---------------------------------------------------------
    def update_task(self, task_id: str, updates: TaskUpdate) -> TaskModel:
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        old_goal = task.goal_id

        for field in ["title", "description", "goal_id", "deadline", "priority", "status"]:
            value = getattr(updates, field, None)
            if value is not None:
                setattr(task, field, value)

        task.updated_at = datetime.utcnow()

        if self.goals_service:
            if old_goal:
                self.goals_service.sync_goal_progress_from_tasks(old_goal)
            if task.goal_id:
                self.goals_service.sync_goal_progress_from_tasks(task.goal_id)

        self._trigger_sync()
        return task

    # ---------------------------------------------------------
    # DELETE TASK
    # ---------------------------------------------------------
    def delete_task(self, task_id: str) -> TaskModel:
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        removed = self.tasks.pop(task_id)

        if self.goals_service and removed.goal_id:
            self.goals_service.sync_goal_progress_from_tasks(removed.goal_id)

        self._trigger_sync()
        return removed

    # ---------------------------------------------------------
    # ASSIGN TO GOAL
    # ---------------------------------------------------------
    def assign_task(self, task_id: str, goal_id: str) -> TaskModel:
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError(f"Task {task_id} not found")

        old_goal = task.goal_id
        task.goal_id = goal_id
        task.updated_at = datetime.utcnow()

        if self.goals_service:
            if old_goal:
                self.goals_service.sync_goal_progress_from_tasks(old_goal)
            self.goals_service.sync_goal_progress_from_tasks(goal_id)

        self._trigger_sync()
        return task

    # ---------------------------------------------------------
    # GENERATE TASK FROM GOAL
    # ---------------------------------------------------------
    def generate_task_from_goal(self, goal) -> TaskModel:
        now = datetime.utcnow()
        task_id = uuid4().hex

        task = TaskModel(
            id=task_id,
            title=f"Task: {goal.title}",
            description=goal.description,
            goal_id=goal.id,
            deadline=goal.deadline,
            priority=goal.priority,
            status="pending",
            created_at=now,
            updated_at=now,
        )

        self.tasks[task_id] = task

        if self.goals_service:
            self.goals_service.sync_goal_progress_from_tasks(goal.id)

        self._trigger_sync()
        return task

    # ---------------------------------------------------------
    # SYNC FROM NOTION (DOWN)
    # ---------------------------------------------------------
    def sync_from_notion(self, data: Dict[str, Any]):
        task_id = data["id"]
        existing = self.tasks.get(task_id)

        goal_id = data.get("goal")[0] if data.get("goal") else None

        if existing:
            updates = TaskUpdate(
                title=data.get("name"),
                description=data.get("description"),
                goal_id=goal_id,
                deadline=data.get("due_date"),
                priority=data.get("priority"),
                status=data.get("status"),
            )
            return self.update_task(task_id, updates)

        new_task = TaskCreate(
            title=data.get("name"),
            description=data.get("description"),
            goal_id=goal_id,
            deadline=data.get("due_date"),
            priority=data.get("priority"),
        )

        return self.create_task(new_task, forced_id=task_id)

    # ---------------------------------------------------------
    # GET ALL
    # ---------------------------------------------------------
    def get_all(self):
        return list(self.tasks.values())