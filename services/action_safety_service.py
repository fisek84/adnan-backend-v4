# services/action_safety_service.py

"""
Safety & Validation Layer (Korak 8.5)

Ovaj modul obezbjeđuje:
- sigurnosne provjere prije izvršenja bilo koje AI akcije
- validaciju direktiva
- validaciju parametara
- zaštitu od opasnih workflow-a

NIŠTA se ne izvršava.
Ovo je samo zaštitni sloj koji vraća "allowed" ili "blocked".
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

        # 1. Provjera da li je akcija eksplicitno blokirana
        if directive in self.BLOCKED_ACTIONS:
            return {
                "allowed": False,
                "reason": f"Directive '{directive}' is blocked for safety reasons."
            }

        # 2. Minimalna validacija parametara
        if params is None:
            params = {}

        if not isinstance(params, dict):
            return {
                "allowed": False,
                "reason": "Invalid parameter format. Expected a dict."
            }

        # 3. Provjera praznih ključeva
        for key, value in params.items():
            if key is None or key == "":
                return {
                    "allowed": False,
                    "reason": "Parameter keys cannot be empty."
                }

        # 4. Sve OK — akcija je dozvoljena
        return {
            "allowed": True
        }

    # ------------------------------------------
    # Validacija workflow-a prije izvršenja
    # ------------------------------------------
    def validate_workflow(self, workflow: Dict[str, Any]) -> Dict[str, Any]:

        # Workflow mora imati listu koraka
        steps: List[Dict[str, Any]] = workflow.get("steps", [])

        if not isinstance(steps, list):
            return {
                "allowed": False,
                "reason": "Workflow malformed: 'steps' must be a list."
            }

        # Maksimalan broj koraka
        if len(steps) > self.MAX_WORKFLOW_STEPS:
            return {
                "allowed": False,
                "reason": f"Workflow too long. Limit is {self.MAX_WORKFLOW_STEPS} steps."
            }

        # Validacija svakog koraka
        for index, step in enumerate(steps):
            directive = step.get("directive")
            params = step.get("params", {})

            if not directive:
                return {
                    "allowed": False,
                    "reason": f"Missing directive at step {index}."
                }

            # Ako ijedna akcija nije validna → workflow je blokiran
            single_check = self.validate_action(directive, params)
            if not single_check["allowed"]:
                return {
                    "allowed": False,
                    "reason": f"Workflow blocked at step {index}: {single_check['reason']}"
                }

        # Sve OK — workflow dozvoljen
        return {
            "allowed": True
        }
