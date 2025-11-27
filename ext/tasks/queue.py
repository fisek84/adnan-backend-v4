import uuid
from ext.tasks.db import save_task
from ext.tasks.worker import execute_task

def enqueue_task(payload: dict):
    """
    Kreira novi task, sprema ga u SQLite i odmah pokreće worker.
    """
    task_id = str(uuid.uuid4())
    save_task(task_id, str(payload))
    execute_task(task_id)
    return task_id
