# services/action_safety_service.py

"""
Safety & Validation Layer (CANONICAL)

Uloga:
- sigurnosne provjere prije izvršenja
- validacija sistemskih komandi
- zaštita od opasnih workflow-a

NIŠTA se ne izvršava.
Ovo je READ-ONLY guard sloj.
"""

from typing import Dict, Any, List
from models.ai_command import AICommand


class ActionSafetyService:

    # ------------------------------------------
    # Blokirane radnje — AI ih nikada ne smije izvršiti
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
        Raises exception if blocked.
        """

        if not command or not isinstance(command, AICommand):
            raise ValueError("Invalid AICommand.")

        if not command.command:
            raise ValueError("Missing command directive.")

        if command.command in self.BLOCKED_ACTIONS:
            raise PermissionError(
                f"Command '{command.command}' is blocked for safety reasons."
            )

        if command.command == "workflow":
            self._validate_workflow(command.input or {})

        self._validate_params(command.input or {})

    # ============================================================
    # BACKWARD-COMPATIBILITY ADAPTER (NE DIRATI)
    # ============================================================
    def validate_action(self, directive: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Compatibility adapter for ExecutionGovernanceService.
        READ-ONLY. No execution.
        """

        if not directive:
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
        except Exception as e:
            return {
                "allowed": False,
                "reason": str(e),
            }

        if directive == "workflow":
            try:
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
            raise ValueError("Invalid parameter format. Expected a dict.")

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

            if not directive or not isinstance(directive, str):
                raise ValueError(f"Missing or invalid directive at step {index}.")

            if directive in self.BLOCKED_ACTIONS:
                raise PermissionError(
                    f"Workflow blocked at step {index}: directive '{directive}' is blocked."
                )

            self._validate_params(params or {})
