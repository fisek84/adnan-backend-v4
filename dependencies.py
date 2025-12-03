import os
from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.projects_service import ProjectsService
from services.notion_service import NotionService
from services.notion_sync_service import NotionSyncService

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

    # ----------------------------------------------------
    # 1. NOTION SERVICE
    # ----------------------------------------------------
    _notion = NotionService(
        api_key=os.getenv("NOTION_API_KEY"),
        goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
        tasks_db_id=os.getenv("NOTION_TASKS_DB_ID"),
        projects_db_id=os.getenv("NOTION_PROJECTS_DB_ID"),

        # Optional:
        active_goals_db_id=os.getenv("NOTION_ACTIVE_GOALS_DB_ID"),
        agent_exchange_db_id=os.getenv("NOTION_AGENT_EXCHANGE_DB_ID"),
        agent_projects_db_id=os.getenv("NOTION_AGENT_PROJECTS_DB_ID"),
        ai_weekly_summary_db_id=os.getenv("NOTION_AI_WEEKLY_SUMMARY_DB_ID"),
        blocked_goals_db_id=os.getenv("NOTION_BLOCKED_GOALS_DB_ID"),
        completed_goals_db_id=os.getenv("NOTION_COMPLETED_GOALS_DB_ID"),
        lead_db_id=os.getenv("NOTION_LEAD_DB_ID"),
        kpi_db_id=os.getenv("NOTION_KPI_DB_ID"),
        flp_db_id=os.getenv("NOTION_FLP_DB_ID"),
    )

    set_notion_service(_notion)

    # ----------------------------------------------------
    # 2. Local backend services
    # ----------------------------------------------------
    _goals = GoalsService()
    _tasks = TasksService(_notion)
    _projects = ProjectsService()

    # Bind services between each other
    _projects.bind_goals_service(_goals)
    _projects.bind_tasks_service(_tasks)

    set_goals_service(_goals)
    set_tasks_service(_tasks)
    set_projects_service(_projects)

    # ----------------------------------------------------
    # 3. Notion Sync Service
    # ----------------------------------------------------
    _sync = NotionSyncService(
        notion_service=_notion,
        goals_service=_goals,
        tasks_service=_tasks,
        projects_service=_projects,
        goals_db_id=os.getenv("NOTION_GOALS_DB_ID"),
        tasks_db_id=os.getenv("NOTION_TASKS_DB_ID"),
        projects_db_id=os.getenv("NOTION_PROJECTS_DB_ID"),
    )

    _projects.bind_sync_service(_sync)
    _goals.bind_sync_service(_sync)
    _tasks.bind_sync_service(_sync)

    set_sync_service(_sync)

    print("🔧 Services initialized inside dependencies.py")
