# dependencies.py

# globalne instance servisa — postavlja ih main.py u startup_event
goals_service_instance = None
tasks_service_instance = None
notion_service_instance = None

# dependency funkcije koje koriste routeri
def get_goals_service():
    return goals_service_instance

def get_tasks_service():
    return tasks_service_instance

def get_notion_service():
    return notion_service_instance