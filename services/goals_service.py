import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Optional, List

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
    # SAFE ASYNC TRIGGER
    # ============================================================
    def _trigger_sync(self):
        if not self.sync_service:
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.sync_service.debounce_goals_sync())
        except RuntimeError:
            asyncio.get_event_loop().create_task(self.sync_service.debounce_goals_sync())

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
            children = (
                self.goals[current].children
                if current in self.goals
                else []
            )
            stack.extend(children)
        return False

    # ============================================================
    # CREATE GOAL (supports notion_id)
    # ============================================================
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

            # ⭐ KLJUČNO — za Notion delete & sync
            notion_id=notion_id
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

        # basic fields
        for field in ["title", "description", "deadline", "priority", "status", "progress"]:
            val = getattr(updates, field, None)
            if val is not None:
                setattr(goal, field, val)

        # parent change
        if new_parent is not None and new_parent != old_parent:
            # remove from old parent
            if old_parent:
                p = self.goals.get(old_parent)
                if p and goal_id in p.children:
                    p.children.remove(goal_id)

            # add to new parent
            if new_parent:
                if self._would_create_cycle(new_parent, goal_id):
                    raise ValueError("Hierarchy cycle detected.")

                p = self.goals.get(new_parent)
                if p and goal_id not in p.children:
                    p.children.append(goal_id)

            goal.parent_id = new_parent

        goal.updated_at = self._now()
        self._trigger_sync()
        return goal

    # ============================================================
    # DELETE GOAL (supports Notion delete)
    # ============================================================
    def delete_goal(self, goal_id: str) -> GoalModel:
        goal = self.goals.get(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        # unlink from parent
        if goal.parent_id:
            p = self.goals.get(goal.parent_id)
            if p and goal_id in p.children:
                p.children.remove(goal_id)

        removed = self.goals.pop(goal_id)

        # orphan children become top-level
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
            notion_id=None
        )

        for g in selected:
            self.goals.pop(g.id, None)

        self.goals[merged_id] = merged
        self._trigger_sync()
        return merged

    # ============================================================
    # GET ALL
    # ============================================================
    def get_all(self) -> List[GoalModel]:
        return list(self.goals.values())