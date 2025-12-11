from ext.tasks.db import update_task, get_task
from ext.documents.orchestrator import orchestrate_document

def execute_task(task_id: str):
    # update status to running
    update_task(task_id, "running")

    # retrieve stored payload
    payload_raw = get_task(task_id)["payload"]

    # convert stored string back to dict
    payload = eval(payload_raw)

    # run the document orchestration
    result = orchestrate_document(payload)

    # mark task as done
    update_task(task_id, "done", str(result))
