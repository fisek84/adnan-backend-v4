from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.projects_service import ProjectsService      # ⬅️ DODANO
from services.notion_service import NotionService
import os

# GLOBAL SINGLETON INSTANCES
_goals: GoalsService | None = None
_tasks: TasksService | None = None
_projects: ProjectsService | None = None     # ⬅️ DODANO
_notion: NotionService | None = None


# ======================================
# SETTERS
# ======================================
def set_goals_service(instance: GoalsService):
    global _goals
    _goals = instance


def set_tasks_service(instance: TasksService):
    global _tasks
    _tasks = instance


def set_projects_service(instance: ProjectsService):      # ⬅️ DODANO
    global _projects
    _projects = instance


def set_notion_service(instance: NotionService):
    global _notion
    _notion = instance


# ======================================
# GETTERS
# ======================================
def get_goals_service():
    if _goals is None:
        raise RuntimeError("GoalsService has not been initialized.")
    return _goals


def get_tasks_service():
    if _tasks is None:
        raise RuntimeError("TasksService has not been initialized.")
    return _tasks


def get_projects_service():                               # ⬅️ DODANO
    if _projects is None:
        raise RuntimeError("ProjectsService has not been initialized.")
    return _projects


def get_notion_service():
    if _notion is None:
        raise RuntimeError("NotionService has not been initialized.")
    return _notion


# ======================================
# INIT SERVICES (CALLED FROM main.py)
# ======================================
def init_services():
    """
    Called once inside startup_event() in main.py.
    Creates and registers NotionService, GoalsService, TasksService, ProjectsService.
    """

    global _notion, _goals, _tasks, _projects

    # Create Notion service
    _notion = NotionService(
        api_key=os.getenv("NOTION_API_KEY"),
        goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
        tasks_db_id=os.getenv("NOTION_TASKS_DB_ID")
    )

    # Local DB services
    _goals = GoalsService()

    # TasksService *requires* NotionService
    _tasks = TasksService(_notion)

    # NEW — ProjectsService global instance
    _projects = ProjectsService()                          # ⬅️ DODANO

    print("🔧 Services initialized inside dependencies.py")
