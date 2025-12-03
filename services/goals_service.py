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
            asyncio.get_event_loop().create_task(
                self.sync_service.debounce_goals_sync()
            )

    # ============================================================
    # HELPERS
    # ============================================================
    def _now(self):
        return datetime.now(timezone.utc)

    # ============================================================
    # REQUIRED BY SYNC SERVICE
    # ============================================================
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

    # ============================================================
    # DETECT CYCLES
    # ============================================================
    def _would_create_cycle(self, parent_id: str, child_id: str) -> bool:
        stack = [child_id]
        while stack:
            current = stack.pop()
            if current == parent_id:
                return True
            children = self.goals[current].children if current in self.goals else []
            stack.extend(children)
        return False

    # ============================================================
    # CREATE GOAL
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
                p = self.goals.get(old_parent)
                if p and goal_id in p.children:
                    p.children.remove(goal_id)

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
    # DELETE GOAL
    # ============================================================
    def delete_goal(self, goal_id: str) -> GoalModel:
        goal = self.goals.get(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        if goal.parent_id:
            p = self.goals.get(goal.parent_id)
            if p and goal_id in p.children:
                p.children.remove(goal_id)

        removed = self.goals.pop(goal_id)

        for g in self.goals.values():
            if g.parent_id == goal_id:
                g.parent_id = None
                g.updated_at = self._now()

        self._trigger_sync()
        return removed

    # ============================================================
    # GET ALL
    # ============================================================
    def get_all(self) -> List[GoalModel]:
        return list(self.goals.values())

    # ============================================================
    # K13 — GOAL GRAPH (READ-ONLY INTELLIGENCE)
    # ============================================================
    def build_goal_graph(self) -> Dict[str, dict]:
        """
        Vraća strukturu:
        {
            goal_id: {
                "id": ...,
                "parent": ...,
                "children": [...],
                "depth": ...,
                "is_root": True/False
            }
        }
        """
        graph = {}
        for gid, goal in self.goals.items():
            parent = goal.parent_id
            graph[gid] = {
                "id": gid,
                "parent": parent,
                "children": goal.children,
                "is_root": parent is None,
                "depth": self._compute_depth(gid),
            }
        return graph

    def _compute_depth(self, goal_id: str) -> int:
        depth = 0
        current = self.goals.get(goal_id)
        while current and current.parent_id:
            depth += 1
            current = self.goals.get(current.parent_id)
        return depth

    def get_root_goals(self) -> List[str]:
        return [gid for gid, g in self.goals.items() if g.parent_id is None]

    def get_subgoals(self, goal_id: str) -> List[str]:
        g = self.goals.get(goal_id)
        if not g:
            return []
        return g.children

    def find_ultimate_parent(self, goal_id: str) -> Optional[str]:
        current = self.goals.get(goal_id)
        if not current:
            return None
        while current.parent_id:
            current = self.goals.get(current.parent_id)
        return current.id

    # ============================================================
    # K13 — AUTO-DETECT PARENT GOAL (Notion → Backend)
    # ============================================================
    def auto_detect_parent_if_missing(self, goal_page: dict) -> Optional[str]:
        """
        Ako goal u Notion-u ima 'Parent Goal' relation,
        backend ga prepoznaje i vraća kao parent_id.
        """
        props = goal_page.get("properties", {})
        pg = props.get("Parent Goal")

        if not pg or pg.get("type") != "relation":
            return None

        rel = pg.get("relation", [])
        if not rel:
            return None

        raw = rel[0].get("id")
        if not raw:
            return None

        return raw.replace("-", "")
