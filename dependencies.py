import logging
import os
import sqlite3
from typing import Optional

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
from services.agent_router.agent_router import AgentRouter

# Učitamo .env konfiguraciju
if os.getenv("RENDER") != "true":
    load_dotenv(override=False)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# -------------------------------------------------------
# GLOBAL SINGLETON INSTANCES
# -------------------------------------------------------
_notion: Optional[NotionService] = None
_goals: Optional[GoalsService] = None
_tasks: Optional[TasksService] = None
_projects: Optional[ProjectsService] = None
_sync: Optional[NotionSyncService] = None
_write_gateway: Optional[WriteGateway] = None

_memory: Optional[MemoryService] = None
_agent_router: Optional[AgentRouter] = None
_queue: Optional[QueueService] = None
_orchestrator: Optional[OrchestratorService] = None

# SQLite connection
_db_conn: Optional[sqlite3.Connection] = None


# -------------------------------------------------------
# GETTERS (FastAPI Depends uses these)
# -------------------------------------------------------
def get_notion_service() -> Optional[NotionService]:
    return _notion


def get_goals_service() -> Optional[GoalsService]:
    return _goals


def get_tasks_service() -> Optional[TasksService]:
    return _tasks


def get_projects_service() -> Optional[ProjectsService]:
    return _projects


def get_sync_service() -> Optional[NotionSyncService]:
    return _sync


def get_write_gateway() -> Optional[WriteGateway]:
    return _write_gateway


def get_memory_service() -> Optional[MemoryService]:
    return _memory


def get_agent_router() -> Optional[AgentRouter]:
    return _agent_router


def get_queue_service() -> Optional[QueueService]:
    return _queue


def get_orchestrator_service() -> Optional[OrchestratorService]:
    return _orchestrator


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
    global _agent_router
    global _queue
    global _orchestrator

    # Idempotent init: ako su ključni SSOT slojevi već spremni, ne radimo ništa.
    if (
        _notion is not None
        and _goals is not None
        and _tasks is not None
        and _projects is not None
        and _sync is not None
        and _write_gateway is not None
        and _memory is not None
        and _agent_router is not None
        and _queue is not None
        and _orchestrator is not None
    ):
        logger.info(
            "🔁 dependencies.py → init_services() called, but services are already initialized. Skipping."
        )
        return

    logger.info("🔧 Initializing all backend services (dependencies.py)…")

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
    # 4) Memory + AgentRouter (Phase 6/7 shared SSOT singletons)
    # ----------------------------------------
    _memory = MemoryService()
    _agent_router = AgentRouter()
    logger.info("🧠 MemoryService + 🤖 AgentRouter initialized.")

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
