from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.notion_service import NotionService


# GLOBAL SINGLETONS
_notion: NotionService | None = None
_goals: GoalsService | None = None
_tasks: TasksService | None = None


# ------------------------------------------------------
# INITIALIZATION (called from main.py)
# ------------------------------------------------------
def init_services():
    global _notion, _goals, _tasks

    # 1) Create Notion service
    _notion = NotionService()

    # 2) Create Goals service
    _goals = GoalsService(_notion)

    # 3) Create Tasks service
    _tasks = TasksService(_notion)


# ------------------------------------------------------
# GETTERS FOR DEPENDENCY INJECTION
# ------------------------------------------------------
def get_notion_service() -> NotionService:
    if _notion is None:
        raise RuntimeError("NotionService not initialized.")
    return _notion


def get_goals_service() -> GoalsService:
    if _goals is None:
        raise RuntimeError("GoalsService not initialized.")
    return _goals


def get_tasks_service() -> TasksService:
    if _tasks is None:
        raise RuntimeError("TasksService not initialized.")
    return _tasks