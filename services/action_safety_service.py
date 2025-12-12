# services/action_safety_service.py

"""
Safety & Validation Layer (Korak 8.5 / FAZA 11)

Uloga:
- sigurnosne provjere prije izvršenja
- validacija direktiva
- validacija parametara
- zaštita od opasnih workflow-a

NIŠTA se ne izvršava.
Ovo je READ-ONLY guard sloj.
"""

from typing import Dict, Any, List


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

    # ------------------------------------------
    # Validacija pojedinačne akcije
    # ------------------------------------------
    def validate_action(self, directive: str, params: Dict[str, Any]) -> Dict[str, Any]:

        if directive in self.BLOCKED_ACTIONS:
            return {
                "allowed": False,
                "safety_level": "blocked",
                "reason": f"Directive '{directive}' is blocked for safety reasons.",
            }

        if params is None:
            params = {}

        if not isinstance(params, dict):
            return {
                "allowed": False,
                "safety_level": "blocked",
                "reason": "Invalid parameter format. Expected a dict.",
            }

        for key in params.keys():
            if not key:
                return {
                    "allowed": False,
                    "safety_level": "blocked",
                    "reason": "Parameter keys cannot be empty.",
                }

        return {
            "allowed": True,
            "safety_level": "safe",
        }

    # ------------------------------------------
    # Validacija workflow-a prije izvršenja
    # ------------------------------------------
    def validate_workflow(self, workflow: Dict[str, Any]) -> Dict[str, Any]:

        steps: List[Dict[str, Any]] = workflow.get("steps", [])

        if not isinstance(steps, list):
            return {
                "allowed": False,
                "safety_level": "blocked",
                "reason": "Workflow malformed: 'steps' must be a list.",
            }

        if len(steps) > self.MAX_WORKFLOW_STEPS:
            return {
                "allowed": False,
                "safety_level": "blocked",
                "reason": f"Workflow too long. Limit is {self.MAX_WORKFLOW_STEPS} steps.",
            }

        for index, step in enumerate(steps):
            directive = step.get("directive")
            params = step.get("params", {})

            if not directive:
                return {
                    "allowed": False,
                    "safety_level": "blocked",
                    "reason": f"Missing directive at step {index}.",
                }

            check = self.validate_action(directive, params)
            if not check["allowed"]:
                return {
                    "allowed": False,
                    "safety_level": "blocked",
                    "reason": f"Workflow blocked at step {index}: {check['reason']}",
                }

        return {
            "allowed": True,
            "safety_level": "safe",
        }
