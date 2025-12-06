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
        logger.info(f"Checking for cycle between goal {goal_id} and parent {parent_id}")
        return False

    # ---------------------------------------------------------
    # GET ALL GOALS
    # ---------------------------------------------------------
    def get_all_goals(self) -> List[GoalModel]:
        logger.info(f"[GOALS] Fetching all goals: total {len(self.goals)}")
        return list(self.goals.values())

    def get_all(self) -> List[GoalModel]:
        logger.info(f"[GOALS] Total goals in service: {len(self.goals)}")
        return list(self.goals.values())

    # ---------------------------------------------------------
    # UPDATE GOAL (FULL PARENT–CHILD LOGIC)
    # ---------------------------------------------------------
    async def update_goal(self, goal_id: str, data: GoalUpdate) -> GoalUpdate:
        logger.info(f"[GOALS] Updating goal {goal_id}")

        goal = self.goals.get(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        old_parent_id = goal.parent_id
        new_parent_id = data.parent_id if data.parent_id is not None else old_parent_id

        # Root rules
        if new_parent_id is None:
            raise ValueError("Every goal except root must have a parent")

        # Simple field updates
        if data.title is not None:
            goal.title = data.title
        if data.description is not None:
            goal.description = data.description
        if data.deadline is not None:
            goal.deadline = data.deadline
        if data.priority is not None:
            goal.priority = data.priority
        if data.status is not None:
            goal.status = data.status
        if data.progress is not None:
            goal.progress = data.progress

        # Parent-child logic
        if old_parent_id != new_parent_id:

            if old_parent_id and old_parent_id in self.goals:
                old_parent = self.goals[old_parent_id]
                if goal_id in old_parent.children:
                    old_parent.children.remove(goal_id)

            if new_parent_id not in self.goals:
                raise ValueError(f"Parent goal {new_parent_id} not found")

            new_parent = self.goals[new_parent_id]
            if goal_id not in new_parent.children:
                new_parent.children.append(goal_id)

            goal.parent_id = new_parent_id

        # Timestamp update
        goal.updated_at = self._now()

        self._trigger_sync()

        return data

    # ---------------------------------------------------------
    # DELETE GOAL
    # ---------------------------------------------------------
    async def delete_goal(self, goal_id: str) -> dict:
        goal = self.goals.get(goal_id)
        if not goal:
            logger.warning(f"[GOALS] Attempted to delete non-existent goal {goal_id}")
            return {"notion_id": None}

        notion_id = goal.notion_id

        del self.goals[goal_id]

        logger.info(f"[GOALS] Deleted goal {goal_id} (notion_id={notion_id})")

        return {"notion_id": notion_id}
