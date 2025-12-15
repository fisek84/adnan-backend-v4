"""
WORKFLOW ORCHESTRATOR — CANONICAL (FAZA 4)

Uloga:
- orkestrira VIŠE AICommand-a u deterministički workflow
- upravlja workflow state machine-om
- NEMA execution logike
- NEMA agent logike
- NEMA write-a
- NEMA governance-a (to je već završeno u FAZI 3)

WorkflowOrchestrator ≠ ExecutionOrchestrator
"""

from typing import Dict, Any, List, Optional
from datetime import datetime
from uuid import uuid4

from models.ai_command import AICommand


class WorkflowOrchestrator:
    """
    High-level workflow coordinator.
    """

    # =========================================================
    # WORKFLOW STATES (CANONICAL)
    # =========================================================
    STATE_CREATED = "CREATED"
    STATE_RUNNING = "RUNNING"
    STATE_BLOCKED = "BLOCKED"
    STATE_FAILED = "FAILED"
    STATE_COMPLETED = "COMPLETED"

    def __init__(self):
        # in-memory registry (kanonski za sada)
        self._workflows: Dict[str, Dict[str, Any]] = {}

    # =========================================================
    # CREATE WORKFLOW
    # =========================================================
    def create_workflow(
        self,
        *,
        name: str,
        commands: List[AICommand],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Kreira workflow definiciju + instancu.
        NE izvršava ništa.
        """

        workflow_id = str(uuid4())
        created_at = datetime.utcnow().isoformat()

        workflow = {
            "workflow_id": workflow_id,
            "name": name,
            "state": self.STATE_CREATED,
            "commands": commands,
            "current_step": 0,
            "created_at": created_at,
            "updated_at": created_at,
            "metadata": metadata or {},
        }

        self._workflows[workflow_id] = workflow
        return workflow.copy()

    # =========================================================
    # START WORKFLOW
    # =========================================================
    def start(self, workflow_id: str) -> Dict[str, Any]:
        workflow = self._require(workflow_id)

        if workflow["state"] != self.STATE_CREATED:
            return workflow.copy()

        workflow["state"] = self.STATE_RUNNING
        workflow["updated_at"] = datetime.utcnow().isoformat()

        return workflow.copy()

    # =========================================================
    # ADVANCE (STEP TRANSITION)
    # =========================================================
    def advance(
        self,
        *,
        workflow_id: str,
        success: bool,
        failure_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Orkestrira workflow korak po korak.
        NE izvršava AICommand — samo pomjera state.
        """

        workflow = self._require(workflow_id)

        if workflow["state"] not in {self.STATE_RUNNING}:
            return workflow.copy()

        if not success:
            workflow["state"] = self.STATE_FAILED
            workflow["failure_reason"] = failure_reason
            workflow["updated_at"] = datetime.utcnow().isoformat()
            return workflow.copy()

        workflow["current_step"] += 1

        if workflow["current_step"] >= len(workflow["commands"]):
            workflow["state"] = self.STATE_COMPLETED
        else:
            workflow["state"] = self.STATE_RUNNING

        workflow["updated_at"] = datetime.utcnow().isoformat()
        return workflow.copy()

    # =========================================================
    # READ
    # =========================================================
    def get(self, workflow_id: str) -> Dict[str, Any]:
        return self._require(workflow_id).copy()

    def list(self) -> List[Dict[str, Any]]:
        return [wf.copy() for wf in self._workflows.values()]

    # =========================================================
    # INTERNAL
    # =========================================================
    def _require(self, workflow_id: str) -> Dict[str, Any]:
        if workflow_id not in self._workflows:
            raise KeyError("Workflow not found")
        return self._workflows[workflow_id]
