# dependencies.py

from typing import Optional

# GLOBAL SINGLETONS (inicijalno prazni — postavljaju se u startup_event)
_goals_service = None
_tasks_service = None
_notion_service = None


# ===============================
# SETTERS — KORISTI SAMO U startup_event
# ===============================

def set_goals_service(service):
    global _goals_service
    _goals_service = service


def set_tasks_service(service):
    global _tasks_service
    _tasks_service = service


def set_notion_service(service):
    global _notion_service
    _notion_service = service


# ===============================
# GETTERS — KORISTE ROUTERI
# ===============================

def get_goals_service():
    if _goals_service is None:
        raise RuntimeError("GoalsService is not ready yet.")
    return _goals_service


def get_tasks_service():
    if _tasks_service is None:
        raise RuntimeError("TasksService is not ready yet.")
    return _tasks_service


def get_notion_service():
    if _notion_service is None:
        raise RuntimeError("NotionService is not ready yet.")
    return _notion_service
