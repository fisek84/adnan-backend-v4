# dependencies.py

# GLOBAL INSTANCES (set from main.py on startup)
goals_service_instance = None
tasks_service_instance = None
notion_service_instance = None

def get_goals_service():
    return goals_service_instance

def get_tasks_service():
    return tasks_service_instance

def get_notion_service():
    return notion_service_instance