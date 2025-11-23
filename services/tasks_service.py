from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from models.task_create import TaskCreate
from models.task_update import TaskUpdate
from models.task_model import TaskModel


class TasksService:
    """
    Evolia TasksService v2.0
    Stabilno upravlja Task objektima.
    - čisti update mehanizam
    - stabilna validacija
    - precizna integracija sa GoalsService
    - poboljšano Notion sync ponašanje
    """

    goals_service = None
    sync_service = None

    def __init__(self):
        # string → TaskModel
        self.tasks: Dict[str, TaskModel] = {}

    # =========================================================
    # BINDING (INJECTION)
    # =========================================================
    def bind_goals_service(self, goals_service):
        self.goals_service = goals_service

    def bind_sync_service(self, sync_service):
        self.sync_service = sync_service

    # =========================================================
    # INTERNAL: SAFE SYNC TRIGGER
    # =========================================================
    def _trigger_sync(self):
        """
        Pokreće debounce sync prema Notionu ako postoji aktivna asyncio petlja.
        Test okruženje (nema loop) → ignoriše bez greške.
        """
        if not self.sync_service:
            return

        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.sync_service.debounce_tasks_sync())
        except RuntimeError:
            # Nema aktivne event loop (testovi, offline okruženje)
            pass

    # =========================================================
    # UTIL
    # =========================================================
    @staticmethod
    def _now():
        return datetime.now(timezone.utc)

    def _sync_attached_goals(self, old_goal: Optional[str], new_goal: Optional[str]):
        """
        Nakon update/delete operacija, osvježava goal progress.
        """
        if not self.goals_service:
            return

        if old_goal:
            self.goals_service.sync_goal_progress_from_tasks(old_goal)
        if new_goal:
            self.goals_service.sync_goal_progress_from_tasks(new_goal)

    # =========================================================
    # CREATE
    # =========================================================
    def create_task(
        self,
        data: TaskCreate,
        forced_id: Optional[str] = None
    ) -> TaskModel:

        now = self._now()
        task_id = forced_id or uuid4().hex

        task = TaskModel(
            id=task_id,
            title=data.title,
            description=data.description or "",
            goal_id=data.goal_id,
            deadline=data.deadline,
            priority=data.priority,
            status="pending",
            created_at=now,
            updated_at=now,
        )

        self.tasks[task_id] = task

        self._sync_attached_goals(None, data.goal_id)
        self._trigger_sync()

        return task

    # =========================================================
    # UPDATE
    # =========================================================
    def update_task(self, task_id: str, updates: TaskUpdate) -> TaskModel:
        task = self.tasks.get(task_id)
        if not task:
            raise KeyError(f"Task '{task_id}' not found")

        old_goal = task.goal_id

        for field in ["title", "description", "goal_id", "deadline", "priority", "status"]:
            value = getattr(updates, field, None)
            if value is not None:
                setattr(task, field, value)

        task.updated_at = self._now()

        self._sync_attached_goals(old_goal, task.goal_id)
        self._trigger_sync()

        return task

    # =========================================================
    # DELETE
    # =========================================================
    def delete_task(self, task_id: str) -> TaskModel:
        task = self.tasks.get(task_id)
        if not task:
            raise KeyError(f"Task '{task_id}' not found")

        removed = self.tasks.pop(task_id)
        self._sync_attached_goals(removed.goal_id, None)
        self._trigger_sync()

        return removed

    # =========================================================
    # ASSIGN
    # =========================================================
    def assign_task(self, task_id: str, goal_id: str) -> TaskModel:
        task = self.tasks.get(task_id)
        if not task:
            raise KeyError(f"Task '{task_id}' not found")

        old = task.goal_id
        task.goal_id = goal_id
        task.updated_at = self._now()

        self._sync_attached_goals(old, goal_id)
        self._trigger_sync()
        return task

    # =========================================================
    # GENERATE TASK FROM GOAL
    # =========================================================
    def generate_task_from_goal(self, goal) -> TaskModel:
        now = self._now()

        task_id = uuid4().hex
        task = TaskModel(
            id=task_id,
            title=f"Task: {goal.title}",
            description=goal.description or "",
            goal_id=goal.id,
            deadline=goal.deadline,
            priority=goal.priority,
            status="pending",
            created_at=now,
            updated_at=now,
        )

        self.tasks[task_id] = task
        self._sync_attached_goals(None, goal.id)
        self._trigger_sync()

        return task

    # =========================================================
    # SYNC FROM NOTION
    # =========================================================
    def sync_from_notion(self, data: Dict[str, Any]):
        """
        Mapira task iz Notion → lokalni format.
        Task se kreira ili ažurira bez gubitka logike progress sync-a.
        """

        task_id = data["id"]
        existing = self.tasks.get(task_id)

        goal_id = None
        if data.get("goal"):
            rels = data.get("goal")
            if isinstance(rels, list) and rels:
                goal_id = rels[0]

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

        new = TaskCreate(
            title=data.get("name"),
            description=data.get("description"),
            goal_id=goal_id,
            deadline=data.get("due_date"),
            priority=data.get("priority"),
        )
        return self.create_task(new, forced_id=task_id)

    # =========================================================
    # GET ALL
    # =========================================================
    def get_all(self) -> List[TaskModel]:
        return list(self.tasks.values())