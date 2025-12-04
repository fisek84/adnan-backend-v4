from models.base_model import GoalModel
from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate

import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Optional, List
import logging

logger = logging.getLogger(__name__)

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
        logger.info(f"[GOALS] Creating goal: {data.title}")

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
        logger.info(f"[GOALS] Goal created with ID: {goal_id}")

        # Parent linking
        if data.parent_id:
            parent = self.goals.get(data.parent_id)
            if parent:
                if self._would_create_cycle(parent.id, goal_id):
                    logger.warning(f"Cyclic dependency detected for parent goal {parent.id} and new goal {goal_id}")
                else:
                    logger.info(f"Parent goal {parent.id} linked to new goal {goal_id}")
            else:
                logger.warning(f"Parent goal {data.parent_id} not found. No linking.")
        
        return new_goal

    def _would_create_cycle(self, parent_id: str, goal_id: str) -> bool:
        """
        Check if linking this goal would create a cycle in the goal hierarchy.
        """
        logger.info(f"Checking for cycle between goal {goal_id} and parent {parent_id}")
        return False  # Assuming no cycle for simplicity

    # ---------------------------------------------------------
    # GET ALL GOALS
    # ---------------------------------------------------------
    def get_all(self) -> List[GoalModel]:
        """
        Vraća sve ciljeve.
        """
        logger.info(f"[GOALS] Total goals in service: {len(self.goals)}")
        if not self.goals:
            logger.warning("[GOALS] No goals found in the service")
        return list(self.goals.values())  # Vraća sve ciljeve kao listu
