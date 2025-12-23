"""
WORKFLOW INSTANCE — CANONICAL (FAZA 4)

Uloga:
- runtime instanca workflow-a
- prati trenutno stanje, korak i ishode
- NEMA execution logike
- NEMA orchestration logike
- čisti STATE HOLDER

WorkflowInstance ≠ WorkflowDefinition
WorkflowInstance ≠ WorkflowOrchestrator
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from services.workflow_definition import WorkflowDefinition


# ============================================================
# WORKFLOW STATES (RUNTIME)
# ============================================================

STATE_CREATED = "CREATED"
STATE_RUNNING = "RUNNING"
STATE_BLOCKED = "BLOCKED"
STATE_FAILED = "FAILED"
STATE_COMPLETED = "COMPLETED"


# ============================================================
# WORKFLOW INSTANCE
# ============================================================


@dataclass
class WorkflowInstance:
    """
    Runtime workflow instance.
    """

    definition: WorkflowDefinition

    workflow_id: str = field(default_factory=lambda: str(uuid4()))
    state: str = STATE_CREATED
    current_step_index: int = 0

    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    failure_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ========================================================
    # LIFECYCLE
    # ========================================================
    def start(self) -> None:
        if self.state != STATE_CREATED:
            return

        self.definition.validate()
        self.state = STATE_RUNNING
        self._touch()

    def mark_blocked(self, reason: str) -> None:
        self.state = STATE_BLOCKED
        self.failure_reason = reason
        self._touch()

    def mark_failed(self, reason: str) -> None:
        self.state = STATE_FAILED
        self.failure_reason = reason
        self._touch()

    def mark_completed(self) -> None:
        self.state = STATE_COMPLETED
        self._touch()

    # ========================================================
    # STEP CONTROL
    # ========================================================
    def get_current_step(self):
        if self.current_step_index >= len(self.definition.steps):
            return None
        return self.definition.steps[self.current_step_index]

    def advance(self) -> None:
        self.current_step_index += 1

        if self.current_step_index >= len(self.definition.steps):
            self.mark_completed()
        else:
            self._touch()

    # ========================================================
    # SNAPSHOT (READ-ONLY)
    # ========================================================
    def to_dict(self) -> Dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "workflow_name": self.definition.workflow_name,
            "version": self.definition.version,
            "state": self.state,
            "current_step_index": self.current_step_index,
            "current_step": (
                self.get_current_step().step_id if self.get_current_step() else None
            ),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "failure_reason": self.failure_reason,
            "metadata": self.metadata,
            "read_only": True,
        }

    # ========================================================
    # INTERNAL
    # ========================================================
    def _touch(self) -> None:
        self.updated_at = datetime.utcnow().isoformat()
