from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.notion_service import NotionService

# GLOBAL SINGLETON INSTANCES
_goals: GoalsService | None = None
_tasks: TasksService | None = None
_notion: NotionService | None = None


def set_goals_service(instance: GoalsService):
    global _goals
    _goals = instance


def set_tasks_service(instance: TasksService):
    global _tasks
    _tasks = instance


def set_notion_service(instance: NotionService):
    global _notion
    _notion = instance


def get_goals_service() -> GoalsService:
    if _goals is None:
        raise RuntimeError("GoalsService has not been initialized yet.")
    return _goals


def get_tasks_service() -> TasksService:
    if _tasks is None:
        raise RuntimeError("TasksService has not been initialized yet.")
    return _tasks


def get_notion_service() -> NotionService:
    if _notion is None:
        raise RuntimeError("NotionService has not been initialized yet.")
    return _notion