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
    # INTERNAL — FIXED ASYNC TRIGGER
    # ============================================================
    def _trigger_sync(self):
        if not self.sync_service:
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.sync_service.debounce_goals_sync())
        except RuntimeError:
            asyncio.run(self.sync_service.debounce_goals_sync())

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
            children = self.goals.get(current).children if current in self.goals else []
            stack.extend(children)

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
        )

        self.goals[goal_id] = new_goal

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
            val = getattr(updates, field, None)
            if val is not None:
                setattr(goal, field, val)

        if new_parent is not None and new_parent != old_parent:

            if old_parent:
                parent = self.goals.get(old_parent)
                if parent and goal_id in parent.children:
                    parent.children.remove(goal_id)

            if new_parent:
                if self._would_create_cycle(new_parent, goal_id):
                    raise ValueError("Hierarchy cycle detected.")

                parent = self.goals.get(new_parent)
                if parent and goal_id not in parent.children:
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

        if goal.parent_id:
            parent = self.goals.get(goal.parent_id)
            if parent and goal_id in parent.children:
                parent.children.remove(goal_id)

        removed = self.goals.pop(goal_id)

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
        )

        for g in selected:
            self.goals.pop(g.id, None)

        self.goals[merged_id] = merged
        self._trigger_sync()
        return merged

    # ============================================================
    # SYNC FROM NOTION
    # ============================================================
    def sync_from_notion(self, data: Dict[str, Any]) -> GoalModel:
        goal_id = data["id"]
        existing = self.goals.get(goal_id)

        parent = data.get("parent_goal")
        parent_id = parent[0] if parent else None

        if existing:
            return self.update_goal(goal_id, GoalUpdate(
                title=data.get("name"),
                description=data.get("description"),
                deadline=data.get("deadline"),
                parent_id=parent_id,
                status=data.get("status"),
                progress=data.get("progress"),
                priority=None
            ))

        return self.create_goal(
            GoalCreate(
                title=data.get("name"),
                description=data.get("description"),
                deadline=data.get("deadline"),
                parent_id=parent_id,
                priority=None
            ),
            forced_id=goal_id
        )

    # ============================================================
    # UTILITIES
    # ============================================================
    def get_all(self):
        return list(self.goals.values())

    def to_dict(self, goal: GoalModel) -> Dict[str, Any]:
        return {
            "id": goal.id,
            "name": goal.title,
            "description": goal.description,
            "deadline": goal.deadline,
            "parent_goal": [goal.parent_id] if goal.parent_id else [],
            "child_goals": goal.children,
            "status": goal.status,
            "progress": goal.progress,
        }