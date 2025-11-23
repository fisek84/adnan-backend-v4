from uuid import uuid4
from datetime import datetime
from typing import Dict, Any, Optional

from models.goal_create import GoalCreate
from models.goal_update import GoalUpdate
from models.base_model import GoalModel


class GoalsService:
    """
    Centralni servis za upravljanje Goal objektima.
    Kompatibilan sa:
    - TasksService (auto progress update)
    - NotionSyncService (sync up/down + debounce)
    """

    tasks_service = None    # bi-directional reference
    sync_service = None     # backlink na NotionSyncService

    def __init__(self):
        self.goals: dict[str, GoalModel] = {}

    # ---------------------------------------------------------
    # BIND SERVICES
    # ---------------------------------------------------------
    def bind_tasks_service(self, tasks_service):
        self.tasks_service = tasks_service

    def bind_sync_service(self, sync_service):
        self.sync_service = sync_service

    # ---------------------------------------------------------
    # INTERNAL: trigger debounce sync
    # ---------------------------------------------------------
    def _trigger_sync(self):
        if self.sync_service:
            import asyncio
            try:
                asyncio.create_task(self.sync_service.debounce_goals_sync())
            except RuntimeError:
                # Ako nema aktivne async petlje (npr. early startup)
                pass

    # ---------------------------------------------------------
    # CREATE GOAL
    # ---------------------------------------------------------
    def create_goal(self, data: GoalCreate, forced_id: Optional[str] = None) -> GoalModel:
        now = datetime.utcnow()
        goal_id = forced_id or uuid4().hex

        goal = GoalModel(
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

        self.goals[goal_id] = goal

        # auto-link to parent
        if data.parent_id:
            parent = self.goals.get(data.parent_id)
            if parent and goal_id not in parent.children:
                parent.children.append(goal_id)
                parent.updated_at = now

        # trigger sync
        self._trigger_sync()

        return goal

    # ---------------------------------------------------------
    # UPDATE GOAL
    # ---------------------------------------------------------
    def update_goal(self, goal_id: str, updates: GoalUpdate) -> GoalModel:
        goal = self.goals.get(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        for field in [
            "title", "description", "deadline",
            "parent_id", "priority", "status", "progress"
        ]:
            value = getattr(updates, field, None)
            if value is not None:
                setattr(goal, field, value)

        goal.updated_at = datetime.utcnow()

        # trigger sync
        self._trigger_sync()

        return goal

    # ---------------------------------------------------------
    # SYNC FROM NOTION (DOWN)
    # ---------------------------------------------------------
    def sync_from_notion(self, data: Dict[str, Any]) -> GoalModel:
        goal_id = data["id"]
        existing = self.goals.get(goal_id)

        parent_id = data.get("parent_goal")[0] if data.get("parent_goal") else None

        if existing:
            updates = GoalUpdate(
                title=data.get("name"),
                description=data.get("description"),
                deadline=data.get("deadline"),
                parent_id=parent_id,
                priority=None,
                status=data.get("status"),
                progress=data.get("progress"),
            )
            return self.update_goal(goal_id, updates)

        new_goal = GoalCreate(
            title=data.get("name"),
            description=data.get("description"),
            deadline=data.get("deadline"),
            parent_id=parent_id,
            priority=None,
        )

        return self.create_goal(new_goal, forced_id=goal_id)

    # ---------------------------------------------------------
    # AUTO SYNC: TASKS → GOAL progress
    # ---------------------------------------------------------
    def sync_goal_progress_from_tasks(self, goal_id: str):
        if not self.tasks_service:
            return

        tasks = [
            t for t in self.tasks_service.tasks.values()
            if t.goal_id == goal_id
        ]

        if not tasks:
            return

        completed = sum(1 for t in tasks if t.status == "completed")
        total = len(tasks)
        progress = int((completed / total) * 100)

        goal = self.goals.get(goal_id)
        if not goal:
            return

        goal.progress = progress
        if progress == 100:
            goal.status = "completed"

        goal.updated_at = datetime.utcnow()

    # ---------------------------------------------------------
    # DELETE GOAL
    # ---------------------------------------------------------
    def delete_goal(self, goal_id: str) -> GoalModel:
        goal = self.goals.get(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        if goal.parent_id:
            parent = self.goals.get(goal.parent_id)
            if parent and goal_id in parent.children:
                parent.children.remove(goal_id)
                parent.updated_at = datetime.utcnow()

        removed = self.goals.pop(goal_id)

        # trigger sync
        self._trigger_sync()

        return removed

    # ---------------------------------------------------------
    # MERGE GOALS
    # ---------------------------------------------------------
    def merge_goals(self, goal_ids: list[str]) -> GoalModel:
        if len(goal_ids) < 2:
            raise ValueError("Two+ goal IDs required")

        collected = [self.goals[g] for g in goal_ids if g in self.goals]

        now = datetime.utcnow()
        merged_id = uuid4().hex

        merged = GoalModel(
            id=merged_id,
            title=" | ".join(g.title for g in collected),
            description=" | ".join(g.description or "" for g in collected),
            deadline=None,
            parent_id=None,
            priority=None,
            status="pending",
            progress=0,
            children=[],
            created_at=now,
            updated_at=now,
        )

        for g in collected:
            self.goals.pop(g.id, None)

        self.goals[merged_id] = merged

        # trigger sync
        self._trigger_sync()

        return merged

    # ---------------------------------------------------------
    # NLP PROGRESS DETECTION
    # ---------------------------------------------------------
    def compute_auto_progress(self, goal_id: str) -> str:
        goal = self.goals.get(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        text = f"{goal.title} {goal.description or ''}".lower()

        if any(k in text for k in ["done", "finished", "completed", "završeno", "gotovo", "odrađeno"]):
            return "completed"

        if any(k in text for k in ["uradi", "napraviti", "plan", "work", "task"]):
            return "in_progress"

        return "unknown"

    # ---------------------------------------------------------
    # ACCESSORS
    # ---------------------------------------------------------
    def get_all(self):
        return list(self.goals.values())

    # ---------------------------------------------------------
    # TO_DICT (for Notion sync up)
    # ---------------------------------------------------------
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