import asyncio
from uuid import uuid4
from datetime import datetime, timezone
from typing import Dict, Optional, List, Any
import logging
import sqlite3

from models.task_model import TaskModel
from models.task_create import TaskCreate
from models.task_update import TaskUpdate

from services.write_gateway.write_gateway import WriteGateway, WriteEnvelope

logger = logging.getLogger(__name__)


class TasksService:
    """
    DOMAIN TASK SERVICE — KANONSKI

    - radi sa lokalnim TaskModel domenim modelom
    - persisitira u SQLite kao interni storage
    - ne zna za agente direktno
    - sync ka Notion-u ide preko posebnog sync_service sloja (ako postoji)
    """

    goals_service = None  # može se bindowati izvana
    sync_service = None

    def __init__(
        self,
        db_conn: sqlite3.Connection,
        write_gateway: Optional[WriteGateway] = None,
    ):
        self.db = db_conn
        self.tasks: Dict[str, TaskModel] = {}

        # Write Gateway (SSOT)
        self.write_gateway = write_gateway or WriteGateway()
        self.write_gateway.register_handler("tasks_create", self._wg_create_task)
        self.write_gateway.register_handler("tasks_update", self._wg_update_task)
        self.write_gateway.register_handler("tasks_delete", self._wg_delete_task)

        self._create_table()

    # ---------------------------------------------------------
    # BIND METHODS
    # ---------------------------------------------------------

    def bind_goals_service(self, goals_service) -> None:
        self.goals_service = goals_service

    def bind_sync_service(self, sync_service) -> None:
        self.sync_service = sync_service

    # ---------------------------------------------------------
    # DB INIT
    # ---------------------------------------------------------

    def _create_table(self) -> None:
        query = """
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            notion_id TEXT,
            title TEXT NOT NULL,
            description TEXT,
            goal_id TEXT,
            deadline TEXT,
            priority TEXT,
            status TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT
        );
        """
        self.db.execute(query)
        self.db.commit()

    # ---------------------------------------------------------
    # LOAD FROM DB
    # ---------------------------------------------------------

    def load_from_db(self) -> None:
        logger.info("📥 Loading tasks from SQLite DB…")

        cursor = self.db.execute("SELECT * FROM tasks ORDER BY created_at ASC")
        rows = cursor.fetchall()

        self.tasks.clear()

        for row in rows:
            model = TaskModel(
                id=row["id"],
                notion_id=row["notion_id"],
                title=row["title"],
                description=row["description"],
                goal_id=row["goal_id"],
                deadline=row["deadline"],
                priority=row["priority"],
                status=row["status"],
                created_at=datetime.fromisoformat(row["created_at"])
                if row["created_at"]
                else None,
                updated_at=datetime.fromisoformat(row["updated_at"])
                if row["updated_at"]
                else None,
            )
            self.tasks[model.id] = model

        logger.info("🟩 Loaded %d tasks from DB.", len(self.tasks))

    # ---------------------------------------------------------
    # INTERNAL HELPERS
    # ---------------------------------------------------------

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def _save_task_to_db(self, task: TaskModel) -> None:
        query = """
        INSERT OR REPLACE INTO tasks (
            id, notion_id, title, description, goal_id,
            deadline, priority, status,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self.db.execute(
            query,
            (
                task.id,
                getattr(task, "notion_id", None),
                task.title,
                task.description,
                task.goal_id,
                task.deadline,
                task.priority,
                task.status,
                task.created_at.isoformat() if task.created_at else None,
                task.updated_at.isoformat() if task.updated_at else None,
            ),
        )
        self.db.commit()

    def _delete_task_from_db(self, task_id: str) -> None:
        self.db.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        self.db.commit()

    def _wg_execution_id(self, payload: dict) -> str:
        exec_id = payload.get("execution_id") or payload.get("idempotency_key")
        if isinstance(exec_id, str) and exec_id.strip():
            return exec_id.strip()
        return f"exec_{uuid4().hex}"

    def _trigger_sync(self) -> None:
        if not self.sync_service:
            return

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.sync_service.debounce_tasks_sync())
        except RuntimeError:
            asyncio.get_event_loop().create_task(
                self.sync_service.debounce_tasks_sync()
            )

    # ---------------------------------------------------------
    # CREATE TASK (DIRECT)
    # ---------------------------------------------------------

    def create_task(
        self,
        data: TaskCreate,
        *,
        forced_id: Optional[str] = None,
        notion_id: Optional[str] = None,
    ) -> TaskModel:
        if isinstance(data, dict):
            title = data.get("title")
            description = data.get("description")
            goal_id = data.get("goal_id")
            deadline = data.get("deadline")
            priority = data.get("priority")
            status = data.get("status") or "pending"
        else:
            title = data.title
            description = data.description
            goal_id = getattr(data, "goal_id", None)
            deadline = data.deadline
            priority = data.priority
            status = data.status or "pending"

        logger.info("[TASKS] Creating task: %s", title)

        now = self._now()
        task_id = forced_id or uuid4().hex

        new_task = TaskModel(
            id=task_id,
            notion_id=notion_id,
            title=title,
            description=description,
            goal_id=goal_id,
            deadline=deadline,
            priority=priority,
            status=status,
            created_at=now,
            updated_at=now,
        )

        self.tasks[task_id] = new_task
        self._save_task_to_db(new_task)

        return new_task

    # ---------------------------------------------------------
    # PUBLIC READ APIS
    # ---------------------------------------------------------

    def get_all(self) -> List[TaskModel]:
        return list(self.tasks.values())

    def get_all_tasks(self) -> List[TaskModel]:
        return list(self.tasks.values())

    # ---------------------------------------------------------
    # UPDATE / DELETE (DIRECT)
    # ---------------------------------------------------------

    def update_task(self, task_id: str, data: TaskUpdate | dict) -> TaskModel:
        task = self.tasks.get(task_id)
        if not task:
            raise KeyError(f"Task {task_id} not found")

        if isinstance(data, dict):
            payload = data
        else:
            payload = data.dict(exclude_unset=True)

        if "title" in payload:
            task.title = payload["title"]
        if "description" in payload:
            task.description = payload["description"]
        if "goal_id" in payload:
            task.goal_id = payload["goal_id"]
        if "deadline" in payload:
            task.deadline = payload["deadline"]
        if "priority" in payload:
            task.priority = payload["priority"]
        if "status" in payload:
            task.status = payload["status"]

        task.updated_at = self._now()
        self._save_task_to_db(task)
        self._trigger_sync()

        return task

    def delete_task(self, task_id: str) -> TaskModel:
        task = self.tasks.get(task_id)
        if not task:
            raise KeyError(f"Task {task_id} not found")

        del self.tasks[task_id]
        self._delete_task_from_db(task_id)
        self._trigger_sync()

        logger.info("[TASKS] Deleted task %s", task_id)

        return task

    # ---------------------------------------------------------
    # ASSIGN / REORDER / GENERATE
    # ---------------------------------------------------------

    def assign_task(self, task_id: str, goal_id: str) -> TaskModel:
        task = self.tasks.get(task_id)
        if not task:
            raise KeyError(f"Task {task_id} not found")

        task.goal_id = goal_id
        task.updated_at = self._now()
        self._save_task_to_db(task)
        self._trigger_sync()

        return task

    def reorder_tasks(self, ordered_ids: List[str]) -> List[TaskModel]:
        """
        Re-assigns internal order of tasks according to ordered_ids.
        DB pamtimo bez posebnog order polja – testovi gledaju redoslijed u dict-u.
        """
        for task_id in ordered_ids:
            task = self.tasks.get(task_id)
            if not task:
                continue
            task.updated_at = self._now()
            self._save_task_to_db(task)

        # držimo interni dict u istom redoslijedu
        self.tasks = {tid: self.tasks[tid] for tid in ordered_ids if tid in self.tasks}

        self._trigger_sync()
        return [self.tasks[tid] for tid in ordered_ids if tid in self.tasks]

    def generate_task_from_goal(self, goal: Any) -> TaskModel:
        """
        Generates a single task from a goal-like object
        (koristi se u testovima sa FakeGoal).
        """
        title = f"Task: {getattr(goal, 'title', '')}"
        description = getattr(goal, "description", None)
        goal_id = getattr(goal, "id", None)
        deadline = getattr(goal, "deadline", None)
        priority = getattr(goal, "priority", None)

        payload = TaskCreate(
            title=title,
            description=description,
            goal_id=goal_id,
            deadline=deadline,
            priority=priority,
        )
        return self.create_task(payload)

    # ---------------------------------------------------------
    # WRITE GATEWAY HANDLERS
    # ---------------------------------------------------------

    async def _wg_create_task(self, env: WriteEnvelope) -> Dict[str, Any]:
        payload = env.payload or {}
        data = payload.get("data") or {}
        forced_id = payload.get("forced_id")
        notion_id = payload.get("notion_id")

        created = self.create_task(data, forced_id=forced_id, notion_id=notion_id)
        self._trigger_sync()
        return {"task_id": created.id, "notion_id": created.notion_id}

    async def _wg_update_task(self, env: WriteEnvelope) -> Dict[str, Any]:
        payload = env.payload or {}
        task_id = str(payload.get("task_id") or "").strip()
        data = payload.get("data") or {}

        logger.info("[TASKS] WG updating task %s", task_id)

        if not task_id:
            raise ValueError("task_id is required")

        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")

        # legacy direct update – rezultat nam ne treba
        self.update_task(task_id, data)

        return {"task_id": task_id, "updated": True, "data": data}

    async def _wg_delete_task(self, env: WriteEnvelope) -> Dict[str, Any]:
        payload = env.payload or {}
        task_id = str(payload.get("task_id") or "").strip()

        logger.info("[TASKS] WG deleting task %s", task_id)

        if not task_id:
            raise ValueError("task_id is required")

        if task_id not in self.tasks:
            # nothing to delete, but do not error
            return {"deleted": False, "task_id": task_id, "notion_id": None}

        deleted = self.delete_task(task_id)

        return {
            "deleted": True,
            "task_id": deleted.id,
            "notion_id": getattr(deleted, "notion_id", None),
        }

    # ---------------------------------------------------------
    # DEFAULT / DEMO HANDLER (OPTIONAL)
    # ---------------------------------------------------------

    async def _demo_handler(self, env: WriteEnvelope) -> Dict[str, Any]:
        return {
            "noop": True,
            "command": env.command,
            "resource": env.resource,
            "actor_id": env.actor_id,
        }
