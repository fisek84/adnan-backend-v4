from services.goals_service import GoalsService
from services.tasks_service import TasksService
from services.notion_service import NotionService

# GLOBAL SINGLETONI
_goals = GoalsService()
_tasks = TasksService()
_notion = None  # inicijaliziramo u startupu


def set_notion_service(instance: NotionService):
    global _notion
    _notion = instance


def get_goals_service():
    return _goals


def get_tasks_service():
    return _tasks


def get_notion_service():
    return _notion
