import logging
import os
import sqlite3
from dotenv import load_dotenv

# Load .env
load_dotenv()

# Import services
from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.notion_service import NotionService
from services.projects_service import ProjectsService
from services.notion_sync_service import NotionSyncService
from services.write_gateway.write_gateway import WriteGateway


# Logger
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


# -------------------------------------------------------
# INIT SERVICES — Called ONCE from main.py
# -------------------------------------------------------
def init_services():
    global _notion, _goals, _tasks, _projects, _sync, _db_conn, _write_gateway

    logger.info("🔧 Initializing all backend services (dependencies.py)…")

    # ----------------------------------------
    # 1) Init SQLite DB
    # ----------------------------------------
    db_path = os.getenv("GOALS_DB_PATH", "goals.db")
    _db_conn = sqlite3.connect(db_path, check_same_thread=False)
    _db_conn.row_factory = sqlite3.Row

    logger.info(f"🗄 SQLite DB initialized at {db_path}")

    # ----------------------------------------
    # 2) Notion service
    # ----------------------------------------
    _notion = NotionService(
        api_key=os.getenv("NOTION_API_KEY"),
        goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
        tasks_db_id=os.getenv("NOTION_TASKS_DB_ID"),
        projects_db_id=os.getenv("NOTION_PROJECTS_DB_ID")
    )

    # ----------------------------------------
    # 3) WriteGateway (SSOT)
    # ----------------------------------------
    _write_gateway = WriteGateway()

    # ----------------------------------------
    # 4) Local backend services
    # ----------------------------------------
    _goals = GoalsService(_db_conn, write_gateway=_write_gateway)
    _tasks = TasksService(write_gateway=_write_gateway)
    _projects = ProjectsService(write_gateway=_write_gateway)

    # Bind services
    _goals.bind_tasks_service(_tasks)
    _tasks.bind_sync_service(None)  # will bind below
    _projects.bind_goals_service(_goals)

    # ----------------------------------------
    # 5) Sync Service
    # ----------------------------------------
    _sync = NotionSyncService(
        _notion,
        _goals,
        _tasks,
        _projects,
        os.getenv("NOTION_GOALS_DB_ID"),
        os.getenv("NOTION_TASKS_DB_ID"),
        os.getenv("NOTION_PROJECTS_DB_ID")
    )

    # Bind sync service
    _goals.bind_sync_service(_sync)
    _tasks.bind_sync_service(_sync)
    _projects.bind_sync_service(_sync)

    # ----------------------------------------
    # 6) Load goals from DB
    # ----------------------------------------
    _goals.load_from_db()

    logger.info("🟩 dependencies.py → All services initialized successfully.")
