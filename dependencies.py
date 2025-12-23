import logging
import os
import sqlite3
from dotenv import load_dotenv

load_dotenv()

# -----------------------------
# Core domain + integrations
# -----------------------------
from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.notion_service import NotionService
from services.projects_service import ProjectsService
from services.notion_sync_service import NotionSyncService
from services.write_gateway.write_gateway import WriteGateway

# -----------------------------
# Phase 5/6/7 SSOT services
# -----------------------------
from services.queue.queue_service import QueueService
from services.orchestrator.orchestrator_service import OrchestratorService
from services.memory_service import MemoryService
from services.agent_router.agent_router import AgentRouter


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# -------------------------------------------------------
# GLOBAL SINGLETON INSTANCES
# -------------------------------------------------------
_notion: NotionService | None = None
_goals: GoalsService | None = None
_tasks: TasksService | None = None
_projects: ProjectsService | None = None
_sync: NotionSyncService | None = None
_write_gateway: WriteGateway | None = None

_memory: MemoryService | None = None
_agent_router: AgentRouter | None = None
_queue: QueueService | None = None
_orchestrator: OrchestratorService | None = None

# SQLite connection
_db_conn: sqlite3.Connection | None = None


# -------------------------------------------------------
# GETTERS (FastAPI Depends uses these)
# -------------------------------------------------------
def get_notion_service():
    return _notion


def get_goals_service():
    return _goals


def get_tasks_service():
    return _tasks


def get_projects_service():
    return _projects


def get_sync_service():
    return _sync


def get_write_gateway():
    return _write_gateway


def get_memory_service():
    return _memory


def get_agent_router():
    return _agent_router


def get_queue_service():
    return _queue


def get_orchestrator_service():
    return _orchestrator


# -------------------------------------------------------
# INIT SERVICES — Called ONCE from main.py (or startup)
# -------------------------------------------------------
def init_services():
    global (
        _notion,
        _goals,
        _tasks,
        _projects,
        _sync,
        _db_conn,
        _write_gateway,
        _memory,
        _agent_router,
        _queue,
        _orchestrator,
    )

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

    # ----------------------------------------
    # 3) WriteGateway (Phase 5 SSOT)
    # ----------------------------------------
    _write_gateway = WriteGateway()

    # ----------------------------------------
    # 4) Memory + AgentRouter (Phase 6/7 shared SSOT singletons)
    # ----------------------------------------
    _memory = MemoryService()
    _agent_router = AgentRouter()

    # ----------------------------------------
    # 5) Local backend services (wired to WriteGateway)
    # ----------------------------------------
    _goals = GoalsService(_db_conn, write_gateway=_write_gateway)
    _tasks = TasksService(write_gateway=_write_gateway)
    _projects = ProjectsService(write_gateway=_write_gateway)

    # Bind services (domain relations)
    _goals.bind_tasks_service(_tasks)
    # tasks_service koristi sync, a goals_service koristi sync; bindamo sync niže
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

    # ----------------------------------------
    # 7) Load goals from DB
    # ----------------------------------------
    _goals.load_from_db()

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

    logger.info("🟩 dependencies.py → All services initialized successfully.")
