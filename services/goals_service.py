import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List
import logging
import json
import sqlite3

from models.base_model import GoalModel
from models.goal_create import GoalCreate

from services.write_gateway.write_gateway import WriteGateway, WriteEnvelope

logger = logging.getLogger(__name__)


class GoalsService:
    """
    DOMAIN GOAL SERVICE — KANONSKI

    - radi sa lokalnim domenim modelom (GoalModel)
    - persisitira u SQLite kao interni storage
    - ne zna za agente
    - sync ka Notion-u ide preko posebnog sync_service sloja
    """

    tasks_service = None
    sync_service = None

    def __init__(
        self, db_conn: sqlite3.Connection, write_gateway: Optional[WriteGateway] = None
    ):
        self.db = db_conn
        self.goals: Dict[str, GoalModel] = {}

        self.write_gateway = write_gateway or WriteGateway()

        # handlers (SSOT enforcement)
        self.write_gateway.register_handler("goals_create", self._wg_create_goal)
        self.write_gateway.register_handler("goals_update", self._wg_update_goal)
        self.write_gateway.register_handler("goals_delete", self._wg_delete_goal)

        self._create_table()

    # ---------------------------------------------------------
    # BIND METHODS
    # ---------------------------------------------------------

    def bind_tasks_service(self, tasks_service):
        self.tasks_service = tasks_service

    def bind_sync_service(self, sync_service):
        self.sync_service = sync_service

    # ---------------------------------------------------------
    # DB INIT
    # ---------------------------------------------------------

    def _create_table(self):
        query = """
        CREATE TABLE IF NOT EXISTS goals (
            id TEXT PRIMARY KEY,
            notion_id TEXT,
            title TEXT NOT NULL,
            description TEXT,
            deadline TEXT,
            parent_id TEXT,
            priority TEXT,
            status TEXT NOT NULL,
            progress INTEGER,
            children TEXT,
            created_at TEXT,
            updated_at TEXT
        );
        """
        self.db.execute(query)
        self.db.commit()

    # ---------------------------------------------------------
    # LOAD FROM DB
    # ---------------------------------------------------------

    def load_from_db(self):
        logger.info("📥 Loading goals from SQLite DB…")

        cursor = self.db.execute("SELECT * FROM goals")
        rows = cursor.fetchall()

        for row in rows:
            children_list = json.loads(row["children"]) if row["children"] else []

            model = GoalModel(
                id=row["id"],
                notion_id=row["notion_id"],
                title=row["title"],
                description=row["description"],
                deadline=row["deadline"],
                parent_id=row["parent_id"],
                priority=row["priority"],
                status=row["status"],
                progress=row["progress"],
                children=children_list,
                created_at=datetime.fromisoformat(row["created_at"]),
                updated_at=datetime.fromisoformat(row["updated_at"]),
            )

            self.goals[row["id"]] = model

        logger.info(f"🟩 Loaded {len(self.goals)} goals from DB.")

    # ---------------------------------------------------------
    # INTERNAL HELPERS
    # ---------------------------------------------------------

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _trigger_sync(self) -> None:
        if not self.sync_service:
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.sync_service.debounce_goals_sync())
        except RuntimeError:
            asyncio.get_event_loop().create_task(
                self.sync_service.debounce_goals_sync()
            )

    def _save_goal_to_db(self, goal: GoalModel) -> None:
        query = """
        INSERT OR REPLACE INTO goals (
            id, notion_id, title, description, deadline,
            parent_id, priority, status, progress,
            children, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        self.db.execute(
            query,
            (
                goal.id,
                goal.notion_id,
                goal.title,
                goal.description,
                goal.deadline,
                goal.parent_id,
                goal.priority,
                goal.status,
                goal.progress,
                json.dumps(goal.children),
                goal.created_at.isoformat(),
                goal.updated_at.isoformat(),
            ),
        )

        self.db.commit()

    def _delete_goal_from_db(self, goal_id: str) -> None:
        self.db.execute("DELETE FROM goals WHERE id = ?", (goal_id,))
        self.db.commit()

    def _wg_execution_id(self, payload: dict) -> str:
        exec_id = payload.get("execution_id") or payload.get("idempotency_key")
        if isinstance(exec_id, str) and exec_id.strip():
            return exec_id.strip()
        return f"exec_{uuid4().hex}"

    # ---------------------------------------------------------
    # CREATE GOAL (LEGACY DIRECT WRITE)
    # ---------------------------------------------------------

    def create_goal(
        self,
        data: GoalCreate | Dict[str, Any],
        forced_id: Optional[str] = None,
        notion_id: Optional[str] = None,
    ) -> GoalModel:
        if isinstance(data, dict):
            title = data.get("title")
            description = data.get("description")
            deadline = data.get("deadline")
            parent_id = data.get("parent_id")
            priority = data.get("priority")
        else:
            title = data.title
            description = data.description
            deadline = data.deadline
            parent_id = data.parent_id
            priority = data.priority

        logger.info("[GOALS] Creating goal: %s", title)

        now = self._now()
        goal_id = forced_id or uuid4().hex

        new_goal = GoalModel(
            id=goal_id,
            notion_id=notion_id,
            title=title,
            description=description,
            deadline=deadline,
            parent_id=parent_id,
            priority=priority,
            status="pending",
            progress=0,
            children=[],
            created_at=now,
            updated_at=now,
        )

        self.goals[goal_id] = new_goal
        self._save_goal_to_db(new_goal)

        return new_goal

    # ---------------------------------------------------------
    # GET ALL
    # ---------------------------------------------------------

    def get_all(self) -> List[GoalModel]:
        return list(self.goals.values())

    def get_all_goals(self) -> List[GoalModel]:
        return list(self.goals.values())

    # ---------------------------------------------------------
    # UPDATE GOAL (WRITE VIA GATEWAY)
    # ---------------------------------------------------------

    async def update_goal(self, goal_id: str, data: dict) -> Dict[str, Any]:
        envelope = {
            "command": "goals_update",
            "actor_id": str((data or {}).get("actor_id") or "system"),
            "resource": f"goal:{goal_id}",
            "payload": {"goal_id": goal_id, "data": dict(data or {})},
            "task_id": "GOALS_UPDATE",
            "execution_id": self._wg_execution_id(data or {}),
            "metadata": (data or {}).get("metadata")
            if isinstance((data or {}).get("metadata"), dict)
            else None,
            "approval_id": (data or {}).get("approval_id"),
        }
        return await self.write_gateway.write(envelope)

    # ---------------------------------------------------------
    # DELETE GOAL (WRITE VIA GATEWAY)
    # ---------------------------------------------------------

    async def delete_goal(self, goal_id: str) -> Dict[str, Any]:
        envelope = {
            "command": "goals_delete",
            "actor_id": "system",
            "resource": f"goal:{goal_id}",
            "payload": {"goal_id": goal_id},
            "task_id": "GOALS_DELETE",
            "execution_id": f"exec_{uuid4().hex}",
        }
        return await self.write_gateway.write(envelope)

    # ---------------------------------------------------------
    # WRITE GATEWAY HANDLERS (REAL SIDE EFFECTS)
    # ---------------------------------------------------------

    async def _wg_create_goal(self, env: WriteEnvelope) -> Dict[str, Any]:
        payload = env.payload or {}
        data = payload.get("data") or {}
        forced_id = payload.get("forced_id")
        notion_id = payload.get("notion_id")

        created = self.create_goal(data, forced_id=forced_id, notion_id=notion_id)
        self._trigger_sync()
        return {"goal_id": created.id, "notion_id": created.notion_id}

    async def _wg_update_goal(self, env: WriteEnvelope) -> Dict[str, Any]:
        payload = env.payload or {}
        goal_id = str(payload.get("goal_id") or "").strip()
        data = payload.get("data") or {}

        logger.info("[GOALS] Updating goal %s", goal_id)

        goal = self.goals.get(goal_id)
        if not goal:
            raise ValueError(f"Goal {goal_id} not found")

        old_parent_id = goal.parent_id
        new_parent_id = data.get("parent_id", old_parent_id)

        if new_parent_id is None:
            raise ValueError("Every goal except root must have a parent")

        if data.get("title") is not None:
            goal.title = data["title"]
        if data.get("description") is not None:
            goal.description = data["description"]
        if data.get("deadline") is not None:
            goal.deadline = data["deadline"]
        if data.get("priority") is not None:
            goal.priority = data["priority"]
        if data.get("status") is not None:
            goal.status = data["status"]
        if data.get("progress") is not None:
            goal.progress = data["progress"]

        if old_parent_id != new_parent_id:
            if old_parent_id and old_parent_id in self.goals:
                old_parent = self.goals[old_parent_id]
                if goal_id in old_parent.children:
                    old_parent.children.remove(goal_id)
                    self._save_goal_to_db(old_parent)

            if new_parent_id not in self.goals:
                raise ValueError(f"Parent goal {new_parent_id} not found")

            new_parent = self.goals[new_parent_id]
            if goal_id not in new_parent.children:
                new_parent.children.append(goal_id)
                self._save_goal_to_db(new_parent)

            goal.parent_id = new_parent_id

        goal.updated_at = self._now()
        self._save_goal_to_db(goal)

        self._trigger_sync()

        return {"goal_id": goal_id, "updated": True, "data": data}

    async def _wg_delete_goal(self, env: WriteEnvelope) -> Dict[str, Any]:
        payload = env.payload or {}
        goal_id = str(payload.get("goal_id") or "").strip()

        goal = self.goals.get(goal_id)
        if not goal:
            return {"notion_id": None, "deleted": False}

        notion_id = goal.notion_id

        del self.goals[goal_id]
        self._delete_goal_from_db(goal_id)

        logger.info("[GOALS] Deleted goal %s (notion_id=%s)", goal_id, notion_id)

        self._trigger_sync()

        return {"notion_id": notion_id, "deleted": True}

    # ---------------------------------------------------------
    # DEFAULT HANDLER (DEMO)
    # ---------------------------------------------------------

    async def _demo_handler(self, env: WriteEnvelope) -> Dict[str, Any]:
        return {
            "noop": True,
            "command": env.command,
            "resource": env.resource,
            "actor_id": env.actor_id,
        }
