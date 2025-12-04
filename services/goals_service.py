# services/goals_service.py

from models.base_model import GoalModel
from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate

import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Optional, List


class GoalsService:
    tasks_service = None
    sync_service = None

    def __init__(self):
        self.goals: Dict[str, GoalModel] = {}

    # ---------------------------------------------------------
    # BINDING
    # ---------------------------------------------------------
    def bind_tasks_service(self, tasks_service):
        self.tasks_service = tasks_service

    def bind_sync_service(self, sync_service):
        self.sync_service = sync_service

    # ---------------------------------------------------------
    # INTERNAL HELPERS
    # ---------------------------------------------------------
    def _now(self):
        return datetime.now(timezone.utc)

    def _trigger_sync(self):
        """
        Safe async sync trigger
        """
        if not self.sync_service:
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.sync_service.debounce_goals_sync())
        except RuntimeError:
            asyncio.get_event_loop().create_task(
                self.sync_service.debounce_goals_sync()
            )

    def to_dict(self, goal: GoalModel) -> dict:
        return {
            "id": goal.id,
            "notion_id": goal.notion_id,
            "title": goal.title,
            "description": goal.description,
            "deadline": goal.deadline,
            "parent_id": goal.parent_id,
            "priority": goal.priority,
            "status": goal.status,
            "progress": goal.progress,
            "children": goal.children,
            "created_at": goal.created_at,
            "updated_at": goal.updated_at,
        }

    # ---------------------------------------------------------
    # CREATE GOAL
    # ---------------------------------------------------------
    def create_goal(
        self,
        data: GoalCreate,
        forced_id: Optional[str] = None,
        notion_id: Optional[str] = None
    ) -> GoalModel:

        now = self._now()
        goal_id = forced_id or uuid4().hex

        new_goal = GoalModel(
            id=goal_id,
            notion_id=notion_id,
            title=data.title,
            description=data.description,
            deadline=data.deadline,
            parent_id=data.parent_id,
            priority=data.priority,
            status="pending",
            progress=0,
            children=[],
            created_at=now,
            updated_at=now,
        )

        self.goals[goal_id] = new_goal

        # Parent linking
        if data.parent_id:
            parent = self.goals.get(data.parent_id)
            if parent:
                if self._would_create_cycle(parent.id, goal_id):
                    raise ValueError("Hierarchy cycle detected.")

                parent.children.append(goal_id)
                parent.updated_at = now

        self._trigger_sync()
        return new_goal

    # ---------------------------------------------------------
    # GET GOAL BY ID (Required for TasksService)
    # ---------------------------------------------------------
    def get_goal_by_id(self, goal_id: str) -> Optional[GoalModel]:
        return self.goals.get(goal_id)
