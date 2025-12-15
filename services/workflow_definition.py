"""
WORKFLOW DEFINITION — CANONICAL (FAZA 4)

Uloga:
- formalna, DEKLARATIVNA definicija workflow-a
- nema execution logike
- nema orchestration logike
- nema side-effecta
- služi za VALIDACIJU i DETERMINIZAM

WorkflowDefinition ≠ WorkflowInstance
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field


# ============================================================
# WORKFLOW STEP
# ============================================================

@dataclass(frozen=True)
class WorkflowStep:
    """
    Jedan korak u workflow-u.
    """
    step_id: str
    command: str
    payload: Dict[str, Any] = field(default_factory=dict)
    optional: bool = False


# ============================================================
# WORKFLOW DEFINITION
# ============================================================

@dataclass(frozen=True)
class WorkflowDefinition:
    """
    Deklarativna definicija workflow-a.
    """

    workflow_name: str
    steps: List[WorkflowStep]

    description: Optional[str] = None
    version: str = "1.0.0"
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ========================================================
    # VALIDATION
    # ========================================================
    def validate(self) -> None:
        """
        Hard validation — baca exception ako workflow nije kanonski.
        """

        if not self.workflow_name:
            raise ValueError("workflow_name is required")

        if not self.steps or not isinstance(self.steps, list):
            raise ValueError("workflow must contain at least one step")

        seen_ids = set()

        for index, step in enumerate(self.steps):
            if not step.step_id:
                raise ValueError(f"step[{index}] missing step_id")

            if step.step_id in seen_ids:
                raise ValueError(f"duplicate step_id: {step.step_id}")

            seen_ids.add(step.step_id)

            if not step.command:
                raise ValueError(f"step[{step.step_id}] missing command")

            if not isinstance(step.payload, dict):
                raise ValueError(f"step[{step.step_id}] payload must be dict")

    # ========================================================
    # SERIALIZATION (READ-ONLY)
    # ========================================================
    def to_dict(self) -> Dict[str, Any]:
        """
        Safe, deterministic snapshot for UI / storage.
        """
        return {
            "workflow_name": self.workflow_name,
            "description": self.description,
            "version": self.version,
            "steps": [
                {
                    "step_id": s.step_id,
                    "command": s.command,
                    "payload": s.payload,
                    "optional": s.optional,
                }
                for s in self.steps
            ],
            "metadata": self.metadata,
            "read_only": True,
        }
