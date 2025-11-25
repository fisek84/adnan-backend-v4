import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate
from models.base_model import GoalModel


class GoalsService:
    tasks_service = None
    sync_service = None

    def __init__(self):
        self.goals: Dict[str, GoalModel] = {}

    # ============================================================
    # BINDING
    # ============================================================
    def bind_tasks_service(self, tasks_service):
        self.tasks_service = tasks_service

    def bind_sync_service(self, sync_service):
        self.sync_service = sync_service

    # ============================================================
    # SAFE SYNC TRIGGER  (NO asyncio.run)
    # ============================================================
    def _trigger_sync(self):
        if not self.sync_service:
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.sync_service.debounce_goals_sync())
        except RuntimeError:
            # If no loop — create a new one safely
            loop = asyncio.new_event_loop()
            loop.create_task(self.sync_service.debounce_goals_sync())

    # ============================================================
    # HELPERS
    # ============================================================
    def _now(self):
        return datetime.now(timezone.utc)

    def _would_create_cycle(self, parent_id: str, child_id: str) -> bool:
        stack = [child_id]
        while stack:
            current = stack.pop()
            if current == parent_id:
                return True
            if current in self.goals:
                stack.extend(self.goals[current].children)
        return False

    # ============================================================
    # CREATE GOAL
    # ============================================================
    def create_goal(self, data: GoalCreate, forced_id: Optional[str] = None) -> GoalModel:
        now = self._now()
        goal_id = forced_id or uuid4().hex

        new_goal = GoalModel(
            id=goal_id,
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
            notion_id=None,
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

    # ============================================================
    # UPDATE GOAL
    # ============================================================
    def update_goal(self, goal_id: str, updates: GoalUpdate) -> GoalModel:
        goal = self.goals.get(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        old_parent = goal.parent_id
        new_parent = updates.parent_id

        for field in ["title", "description", "deadline", "priority", "status", "progress"]:
            value = getattr(updates, field, None)
            if value is not None:
                setattr(goal, field, value)

        # Handle parent change
        if new_parent is not None and new_parent != old_parent:

            if old_parent and old_parent in self.goals:
                parent = self.goals[old_parent]
                if goal_id in parent.children:
                    parent.children.remove(goal_id)

            if new_parent:
                if self._would_create_cycle(new_parent, goal_id):
                    raise ValueError("Hierarchy cycle detected.")
                if new_parent in self.goals:
                    parent = self.goals[new_parent]
                    if goal_id not in parent.children:
                        parent.children.append(goal_id)

            goal.parent_id = new_parent

        goal.updated_at = self._now()
        self._trigger_sync()
        return goal

    # ============================================================
    # DELETE GOAL
    # ============================================================
    def delete_goal(self, goal_id: str) -> GoalModel:
        goal = self.goals.get(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        # Remove from parent
        if goal.parent_id and goal.parent_id in self.goals:
            parent = self.goals[goal.parent_id]
            if goal_id in parent.children:
                parent.children.remove(goal_id)

        removed = self.goals.pop(goal_id)

        # Orphan children
        for g in self.goals.values():
            if g.parent_id == goal_id:
                g.parent_id = None
                g.updated_at = self._now()

        self._trigger_sync()
        return removed

    # ============================================================
    # MERGE GOALS
    # ============================================================
    def merge_goals(self, goal_ids: List[str]) -> GoalModel:
        if len(goal_ids) < 2:
            raise ValueError("At least two goal IDs required")

        selected = [self.goals[g] for g in goal_ids if g in self.goals]
        now = self._now()
        merged_id = uuid4().hex

        merged = GoalModel(
            id=merged_id,
            title=" | ".join(g.title for g in selected),
            description=" | ".join(g.description or "" for g in selected),
            deadline=None,
            parent_id=None,
            priority=None,
            status="pending",
            progress=0,
            children=[],
            created_at=now,
            updated_at=now,
            notion_id=None,
        )

        for g in selected:
            self.goals.pop(g.id, None)

        self.goals[merged_id] = merged
        self._trigger_sync()
        return merged

    # ============================================================
    # GET ALL GOALS
    # ============================================================
    def get_all(self) -> List[GoalModel]:
        return list(self.goals.values())

    # ============================================================
    # REQUIRED BY SYNC SERVICE
    # ============================================================
    def to_dict(self, g: GoalModel) -> Dict[str, Any]:
        return {
            "id": g.id,
            "title": g.title,
            "description": g.description,
            "deadline": g.deadline,
            "parent_id": g.parent_id,
            "priority": g.priority,
            "status": g.status,
            "progress": g.progress,
            "children": g.children,
            "notion_id": g.notion_id,
        }

    def _replace_id(self, old_id: str, new_id: str):
        if old_id not in self.goals:
            return
        obj = self.goals.pop(old_id)
        obj.id = new_id
        self.goals[new_id] = obj