# services/action_safety_service.py

"""
Safety & Validation Layer (CANONICAL) — FAZA 9

Uloga:
- sigurnosne provjere prije izvršenja
- deterministička validacija komandi
- zaštita od opasnih i nekontrolisanih workflow-a

NIŠTA se ne izvršava.
Ovo je READ-ONLY guard sloj.
"""

from typing import Dict, Any, List
from models.ai_command import AICommand


class ActionSafetyService:
    # ------------------------------------------
    # Blokirane radnje — sistem ih nikada ne smije izvršiti
    # ------------------------------------------
    BLOCKED_ACTIONS = {
        "delete_all",
        "wipe",
        "shutdown_system",
        "dangerous",
        "remove_database",
        "reset_system",
    }

    # ------------------------------------------
    # Maksimalan broj koraka u workflow-u
    # ------------------------------------------
    MAX_WORKFLOW_STEPS = 10

    # ============================================================
    # PUBLIC API (KANONSKI)
    # ============================================================
    def check(self, command: AICommand) -> None:
        """
        Validate AICommand before execution.
        Raises exception if blocked or invalid.
        """

        if not isinstance(command, AICommand):
            raise ValueError("Invalid AICommand.")

        directive = command.command
        params = command.input or {}

        if not isinstance(directive, str) or not directive.strip():
            raise ValueError("Missing command directive.")

        if directive in self.BLOCKED_ACTIONS:
            raise PermissionError(
                f"Command '{directive}' is blocked for safety reasons."
            )

        self._validate_params(params)

        if directive == "workflow":
            self._validate_workflow(params)

    # ============================================================
    # BACKWARD-COMPATIBILITY ADAPTER (NE DIRATI)
    # ============================================================
    def validate_action(self, directive: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compatibility adapter for ExecutionGovernanceService.
        READ-ONLY. No execution.
        """

        if not isinstance(directive, str) or not directive:
            return {
                "allowed": False,
                "reason": "Missing directive.",
            }

        if directive in self.BLOCKED_ACTIONS:
            return {
                "allowed": False,
                "reason": f"Directive '{directive}' is blocked for safety reasons.",
            }

        try:
            self._validate_params(params or {})
            if directive == "workflow":
                self._validate_workflow(params or {})
        except Exception as e:
            return {
                "allowed": False,
                "reason": str(e),
            }

        return {
            "allowed": True,
        }

    # ============================================================
    # INTERNAL HELPERS
    # ============================================================
    def _validate_params(self, params: Dict[str, Any]) -> None:
        if params is None:
            return

        if not isinstance(params, dict):
            raise ValueError("Invalid parameter format. Expected dict.")

        for key in params.keys():
            if not isinstance(key, str) or not key.strip():
                raise ValueError("Parameter keys must be non-empty strings.")

    def _validate_workflow(self, workflow: Dict[str, Any]) -> None:
        if not isinstance(workflow, dict):
            raise ValueError("Workflow payload must be a dict.")

        steps: List[Dict[str, Any]] = workflow.get("steps", [])

        if not isinstance(steps, list):
            raise ValueError("Workflow malformed: 'steps' must be a list.")

        if len(steps) > self.MAX_WORKFLOW_STEPS:
            raise ValueError(
                f"Workflow too long. Limit is {self.MAX_WORKFLOW_STEPS} steps."
            )

        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                raise ValueError(f"Workflow step {index} must be a dict.")

            directive = step.get("directive")
            params = step.get("params", {})

            if not isinstance(directive, str) or not directive.strip():
                raise ValueError(f"Missing or invalid directive at step {index}.")

            if directive in self.BLOCKED_ACTIONS:
                raise PermissionError(
                    f"Workflow blocked at step {index}: directive '{directive}' is blocked."
                )

            self._validate_params(params)
