# services/tasks_service.py

import asyncio
from uuid import uuid4
from datetime.datetime import datetime, timezone
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
        self.notion = notion_service   # ✅ PRIMAMO NotionService

    # ============================================================
    # BINDINGS
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

    def _trigger_sync(self):
        """
        Pokreće debounce sync ako postoji sync_service.
        """
        if not self.sync_service:
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.sync_service.debounce_tasks_sync())
        except RuntimeError:
            asyncio.get_event_loop().create_task(
                self.sync_service.debounce_tasks_sync()
            )

    # ============================================================
    # TO_DICT
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
    # CREATE TASK
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

        self.tasks[task_id] = task

        # Notion create
        res = await self.notion.create_task(task)
        print("DEBUG RES:", res, type(res))

        # ====================================================
        # NORMALIZACIJA RESPONSE-A (rješava TypeError problem)
        # ====================================================
        if isinstance(res, str):
            res = {"ok": False, "error": res}

        if not isinstance(res, dict):
            res = {"ok": False, "error": "Invalid response from Notion"}

        # Osiguramo da 'ok' postoji
        res.setdefault("ok", False)

        # Osiguramo da 'data' postoji i bude dict
        if "data" not in res or not isinstance(res.get("data"), dict):
            res["data"] = {}

        # ====================================================
        # Ako je task uspješno kreiran u Notion → upiši ID
        if res["ok"] and "id" in res["data"]:
            task.notion_id = res["data"]["id"]

        # Trigger sync
        self._trigger_sync()

        return task

    # ============================================================
    # UPDATE
    # ============================================================
    async def update_task(self, task_id: str, updates: TaskUpdate):
        task = self.tasks.get(task_id)
        if not task:
            raise ValueError("Task not found")

        # Local updates
        for field in updates.model_fields:
            val = getattr(updates, field)
            if val is not None:
                setattr(task, field, val)

        task.updated_at = self._now()

        # Sync to Notion
        await self.notion.update_task(task.notion_id, updates)

        self._trigger_sync()

        return task

    # ============================================================
    # DELETE
    # ============================================================
    async def delete_task(self, task_id: str):
        task = self.tasks.get(task_id)
        if not task:
            return {"ok": False, "error": "Task not found"}

        notion_id = task.notion_id

        self.tasks.pop(task_id)

        self._trigger_sync()

        return {"ok": True, "notion_id": notion_id}

    # ============================================================
    # GET ALL
    # ============================================================
    def get_all_tasks(self) -> List[TaskModel]:
        return list(self.tasks.values())
