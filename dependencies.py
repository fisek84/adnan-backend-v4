import logging
from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.notion_service import NotionService
from services.projects_service import ProjectsService
from services.notion_sync_service import NotionSyncService
import os
from dotenv import load_dotenv

# Učitaj varijable iz .env datoteke
load_dotenv()

# Inicijalizacija loggera
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# GLOBAL SINGLETON INSTANCES
_goals: GoalsService | None = None
_tasks: TasksService | None = None
_projects: ProjectsService | None = None
_notion: NotionService | None = None
_sync: NotionSyncService | None = None

# ======================================
# SETTERS
# ======================================
def set_goals_service(instance: GoalsService):
    global _goals
    _goals = instance

def set_tasks_service(instance: TasksService):
    global _tasks
    _tasks = instance

def set_projects_service(instance: ProjectsService):
    global _projects
    _projects = instance

def set_notion_service(instance: NotionService):
    global _notion
    _notion = instance

def set_sync_service(instance: NotionSyncService):
    global _sync
    _sync = instance

# ======================================
# GETTERS
# ======================================
def get_goals_service():
    return _goals

def get_tasks_service():
    return _tasks

def get_projects_service():
    return _projects

def get_notion_service():
    return _notion

def get_sync_service():
    return _sync

# ======================================
# INIT SERVICES (CALLED FROM main.py)
# ======================================
def init_services():
    """
    Initializes all services ONE TIME on startup.
    """
    global _notion, _goals, _tasks, _projects, _sync

    try:
        # 1. NOTION SERVICE
        _notion = NotionService(
            api_key=os.getenv("NOTION_API_KEY"),
            goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
            tasks_db_id=os.getenv("NOTION_TASKS_DB_ID"),
            projects_db_id=os.getenv("NOTION_PROJECTS_DB_ID"),
        )
        set_notion_service(_notion)

        # 2. Local backend services
        _goals = GoalsService()
        _tasks = TasksService(_notion)
        _projects = ProjectsService()

        # Bind services
        _projects.bind_goals_service(_goals)
        _projects.bind_tasks_service(_tasks)
        _tasks.bind_goals_service(_goals)  # Ensure task-service is linked to goals-service

        set_goals_service(_goals)
        set_tasks_service(_tasks)
        set_projects_service(_projects)

        # 3. Notion Sync Service
        _sync = NotionSyncService(
            notion_service=_notion,
            goals_service=_goals,
            tasks_service=_tasks,
            projects_service=_projects,
            goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),  # Add this parameter
            tasks_db_id=os.getenv("NOTION_TASKS_DB_ID"),  # Add this parameter
            projects_db_id=os.getenv("NOTION_PROJECTS_DB_ID")  # Add this parameter
        )

        _projects.bind_sync_service(_sync)
        _goals.bind_sync_service(_sync)
        _tasks.bind_sync_service(_sync)

        set_sync_service(_sync)

        logger.info("🔧 Services initialized inside dependencies.py")

    except Exception as e:
        logger.error(f"Error initializing services: {e}")
        raise e
