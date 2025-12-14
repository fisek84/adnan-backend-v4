import json
from ext.tasks.db import update_task, get_task
from ext.documents.orchestrator import orchestrate_document


def execute_task(task_id: str, *, agent_id: str = "agent.document_orchestrator"):
    # -------------------------------------------------
    # TASK → RUNNING (WITH AGENT OWNERSHIP)
    # -------------------------------------------------
    update_task(
        task_id,
        status="running",
        metadata={
            "agent_id": agent_id,
        },
    )

    try:
        # -------------------------------------------------
        # LOAD TASK PAYLOAD (SAFE)
        # -------------------------------------------------
        task = get_task(task_id)
        payload_raw = task.get("payload")

        if not payload_raw:
            raise ValueError("empty_task_payload")

        payload = json.loads(payload_raw)

        # -------------------------------------------------
        # EXECUTE (DELEGATED ORCHESTRATION)
        # -------------------------------------------------
        result = orchestrate_document(payload)

        # -------------------------------------------------
        # TASK → COMPLETED
        # -------------------------------------------------
        update_task(
            task_id,
            status="completed",
            result=json.dumps(result),
        )

        return {
            "success": True,
            "task_id": task_id,
            "agent_id": agent_id,
        }

    except Exception as e:
        # -------------------------------------------------
        # TASK → FAILED (FAILURE CONTAINMENT)
        # -------------------------------------------------
        update_task(
            task_id,
            status="failed",
            error=str(e),
        )

        return {
            "success": False,
            "task_id": task_id,
            "agent_id": agent_id,
            "error": str(e),
        }
