from typing import Dict, Any, Optional
from services.workflow_orchestrator import WorkflowOrchestrator


class WorkflowEventBridge:
    """
    EVENT → WORKFLOW STATE BRIDGE

    Uloga:
    - prima događaje iz execution / delegation sloja
    - ažurira workflow state
    - NE izvršava
    - NE donosi odluke
    """

    def __init__(self):
        self._workflows = WorkflowOrchestrator()

    # =========================================================
    # EVENTS
    # =========================================================
    def on_workflow_created(self, workflow_id: str) -> Dict[str, Any]:
        return self._workflows.start(workflow_id)

    def on_step_completed(
        self,
        *,
        workflow_id: str,
    ) -> Dict[str, Any]:
        return self._workflows.advance(
            workflow_id=workflow_id,
            success=True,
        )

    def on_step_failed(
        self,
        *,
        workflow_id: str,
        reason: Optional[str],
    ) -> Dict[str, Any]:
        return self._workflows.advance(
            workflow_id=workflow_id,
            success=False,
            failure_reason=reason,
        )

    # =========================================================
    # READ
    # =========================================================
    def snapshot(self, workflow_id: str) -> Dict[str, Any]:
        return self._workflows.get(workflow_id)
