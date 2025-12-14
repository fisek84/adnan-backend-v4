import uuid
import json

from ext.tasks.db import save_task
from ext.tasks.worker import execute_task


def enqueue_task(payload: dict, *, agent_id: str = "agent.document_orchestrator"):
    """
    Kreira novi task, sprema ga i delegira izvršenje
    uz eksplicitni agent ownership.
    """

    task_id = str(uuid.uuid4())

    # -------------------------------------------------
    # SAVE TASK (DETERMINISTIC PAYLOAD)
    # -------------------------------------------------
    save_task(
        task_id=task_id,
        payload=json.dumps(payload),
        metadata={
            "agent_id": agent_id,
        },
    )

    # -------------------------------------------------
    # EXECUTE TASK (OWNED BY AGENT)
    # -------------------------------------------------
    execute_task(task_id, agent_id=agent_id)

    return task_id
