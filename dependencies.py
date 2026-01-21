import logging
import os
import sqlite3
import threading
from typing import Optional

from fastapi import HTTPException
from dotenv import load_dotenv
from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.notion_service import NotionService
from services.projects_service import ProjectsService
from services.notion_sync_service import NotionSyncService
from services.write_gateway.write_gateway import WriteGateway
from services.queue.queue_service import QueueService
from services.orchestrator.orchestrator_service import OrchestratorService
from services.memory_service import MemoryService
from services.memory_read_only import ReadOnlyMemoryService
from services.agent_router.agent_router import AgentRouter

# Učitamo .env konfiguraciju
if os.getenv("RENDER") != "true":
    load_dotenv(override=False)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# -------------------------------------------------------
# GLOBAL SINGLETON INSTANCES
# -------------------------------------------------------
_services_initialized = False
_services_init_lock = threading.Lock()

_notion: Optional[NotionService] = None
_goals: Optional[GoalsService] = None
_tasks: Optional[TasksService] = None
_projects: Optional[ProjectsService] = None
_sync: Optional[NotionSyncService] = None
_write_gateway: Optional[WriteGateway] = None

_memory: Optional[MemoryService] = None
_memory_ro: Optional[ReadOnlyMemoryService] = None

_agent_router: Optional[AgentRouter] = None
_queue: Optional[QueueService] = None
_orchestrator: Optional[OrchestratorService] = None

# SQLite connection
_db_conn: Optional[sqlite3.Connection] = None


# -------------------------------------------------------
# GETTERS (FastAPI Depends uses these)
# -------------------------------------------------------
def _require_service(service: Optional[object], name: str):
    if service is None:
        raise HTTPException(status_code=503, detail=f"Service not configured: {name}")
    return service


def services_status() -> dict:
    """Non-raising status snapshot for health checks / diagnostics."""
    return {
        "initialized": bool(_services_initialized),
        "notion": _notion is not None,
        "goals": _goals is not None,
        "tasks": _tasks is not None,
        "projects": _projects is not None,
        "sync": _sync is not None,
        "write_gateway": _write_gateway is not None,
        "memory": _memory is not None,
        "memory_read_only": _memory_ro is not None,
        "agent_router": _agent_router is not None,
        "queue": _queue is not None,
        "orchestrator": _orchestrator is not None,
        "sqlite": _db_conn is not None,
    }


def get_notion_service() -> NotionService:
    return _require_service(_notion, "notion")  # type: ignore[return-value]


def get_goals_service() -> GoalsService:
    return _require_service(_goals, "goals")  # type: ignore[return-value]


def get_tasks_service() -> TasksService:
    return _require_service(_tasks, "tasks")  # type: ignore[return-value]


def get_projects_service() -> ProjectsService:
    return _require_service(_projects, "projects")  # type: ignore[return-value]


def get_sync_service() -> NotionSyncService:
    return _require_service(_sync, "sync")  # type: ignore[return-value]


def get_write_gateway() -> WriteGateway:
    return _require_service(_write_gateway, "write_gateway")  # type: ignore[return-value]


def get_memory_service() -> MemoryService:
    return _require_service(_memory, "memory")  # type: ignore[return-value]


def get_memory_read_only_service() -> ReadOnlyMemoryService:
    return _require_service(_memory_ro, "memory_read_only")  # type: ignore[return-value]


def get_agent_router() -> AgentRouter:
    return _require_service(_agent_router, "agent_router")  # type: ignore[return-value]


def get_queue_service() -> QueueService:
    return _require_service(_queue, "queue")  # type: ignore[return-value]


def get_orchestrator_service() -> OrchestratorService:
    return _require_service(_orchestrator, "orchestrator")  # type: ignore[return-value]


# -------------------------------------------------------
# INIT SERVICES — Called ONCE from main.py (or startup)
# -------------------------------------------------------
def init_services() -> None:
    """
    Idempotent inicijalizacija svih globalnih servisa.

    Poziva se jednom na startup (npr. iz main.py). Ako su svi
    ključni singletoni već inicijalizirani, funkcija samo vrati.
    """
    global _notion
    global _goals
    global _tasks
    global _projects
    global _sync
    global _db_conn
    global _write_gateway
    global _memory
    global _memory_ro
    global _agent_router
    global _queue
    global _orchestrator
    global _services_initialized

    with _services_init_lock:
        if _services_initialized:
            logger.info("dependencies.py -> init_services skipped (already initialized)")
            return

        # Back-compat guard: if an older version initialized everything without the flag.
        if (
            _notion is not None
            and _goals is not None
            and _tasks is not None
            and _projects is not None
            and _sync is not None
            and _write_gateway is not None
            and _memory is not None
            and _memory_ro is not None
            and _agent_router is not None
            and _queue is not None
            and _orchestrator is not None
        ):
            _services_initialized = True
            logger.info("dependencies.py -> init_services skipped (already initialized)")
            return

        logger.info("dependencies.py -> init_services starting")

        # ----------------------------------------
        # 1) Init SQLite DB
        # ----------------------------------------
        db_path = os.getenv("GOALS_DB_PATH", "goals.db")
        _db_conn = sqlite3.connect(db_path, check_same_thread=False)
        _db_conn.row_factory = sqlite3.Row
        logger.info("🗄 SQLite DB initialized at %s", db_path)

        # ----------------------------------------
        # 2) Notion service
        # ----------------------------------------
        _notion = NotionService(
            api_key=os.getenv("NOTION_API_KEY"),
            goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
            tasks_db_id=os.getenv("NOTION_TASKS_DB_ID"),
            projects_db_id=os.getenv("NOTION_PROJECTS_DB_ID"),
        )
        logger.info("🧠 NotionService initialized.")

        # ----------------------------------------
        # 3) WriteGateway (Phase 5 SSOT)
        # ----------------------------------------
        _write_gateway = WriteGateway()
        logger.info("✍️ WriteGateway initialized.")

        # ----------------------------------------
        # 4) Memory (RW) + Memory (RO) + AgentRouter
        # ----------------------------------------
        _memory = MemoryService()
        _memory_ro = ReadOnlyMemoryService(_memory)
        _agent_router = AgentRouter()
        logger.info(
            "🧠 MemoryService (RW) + 🔒 ReadOnlyMemoryService (RO) + 🤖 AgentRouter initialized."
        )

        # ----------------------------------------
        # 5) Local backend services (wired to WriteGateway)
        # ----------------------------------------
        _goals = GoalsService(_db_conn, write_gateway=_write_gateway)
        _tasks = TasksService(_db_conn, write_gateway=_write_gateway)
        _projects = ProjectsService(write_gateway=_write_gateway)
        logger.info("📌 GoalsService, TasksService, ProjectsService initialized.")

        # Bind services (domain relations)
        _goals.bind_tasks_service(_tasks)
        _projects.bind_goals_service(_goals)

        # ----------------------------------------
        # 6) Sync Service
        # ----------------------------------------
        _sync = NotionSyncService(
            _notion,
            _goals,
            _tasks,
            _projects,
            os.getenv("NOTION_GOALS_DB_ID"),
            os.getenv("NOTION_TASKS_DB_ID"),
            os.getenv("NOTION_PROJECTS_DB_ID"),
        )

        # Bind sync service
        _goals.bind_sync_service(_sync)
        _tasks.bind_sync_service(_sync)
        _projects.bind_sync_service(_sync)
        logger.info("🔄 NotionSyncService initialized and bound.")

        # ----------------------------------------
        # 7) Load goals from DB
        # ----------------------------------------
        _goals.load_from_db()
        logger.info("📥 Goals loaded from DB.")

        # ----------------------------------------
        # 8) Queue + Orchestrator (Phase 7 SSOT)
        # ----------------------------------------
        _queue = QueueService()
        _orchestrator = OrchestratorService(
            queue=_queue,
            memory=_memory,
            agent_router=_agent_router,
            write_gateway=_write_gateway,
        )

        logger.info("🧵 QueueService + 🎛 OrchestratorService initialized.")
        logger.info("🟩 dependencies.py → All services initialized successfully.")
        _services_initialized = True
        logger.info("dependencies.py -> init_services completed")
