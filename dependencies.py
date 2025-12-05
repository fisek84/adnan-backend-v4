import logging
import os
from dotenv import load_dotenv

# Load .env
load_dotenv()

# Import services
from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.notion_service import NotionService
from services.projects_service import ProjectsService
from services.notion_sync_service import NotionSyncService


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


# -------------------------------------------------------
# INIT SERVICES — Called ONCE from main.py
# -------------------------------------------------------
def init_services():
    global _notion, _goals, _tasks, _projects, _sync

    logger.info("🔧 Initializing all backend services (dependencies.py)…")

    # 1) Notion service
    _notion = NotionService(
        api_key=os.getenv("NOTION_API_KEY"),
        goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
        tasks_db_id=os.getenv("NOTION_TASKS_DB_ID"),
        projects_db_id=os.getenv("NOTION_PROJECTS_DB_ID")
    )

    # 2) Local backend services
    _goals = GoalsService()
    _tasks = TasksService(_notion)
    _projects = ProjectsService()

    # Bind services
    _goals.bind_tasks_service(_tasks)
    _tasks.bind_goals_service(_goals)
    _projects.bind_goals_service(_goals)

    # 3) Sync Service
    _sync = NotionSyncService(
        _notion,
        _goals,
        _tasks,
        _projects,
        os.getenv("NOTION_GOALS_DB_ID"),
        os.getenv("NOTION_TASKS_DB_ID"),
        os.getenv("NOTION_PROJECTS_DB_ID")
    )

    # Bind sync service to all others
    _goals.bind_sync_service(_sync)
    _tasks.bind_sync_service(_sync)
    _projects.bind_sync_service(_sync)

    logger.info("🟩 dependencies.py → All services initialized successfully.")
