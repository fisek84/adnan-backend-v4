# services/action_workflow_service.py

"""
Workflow Execution Engine (Korak 8.4)

Ovaj servis:
- prima AI definisane workflow-e
- izvršava ih korak po korak
- koristi ActionExecutionService za svaku akciju
- ne prekida cijeli workflow osim u kritičnoj grešci
- vraća listu rezultata za svaki korak
"""

from typing import Dict, Any, List
from services.action_execution_service import ActionExecutionService


class ActionWorkflowService:
    def __init__(self):
        self.executor = ActionExecutionService()

    def execute_workflow(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """
        Workflow format:
        {
            "type": "workflow",
            "steps": [
                {"directive": "...", "params": {...}},
                {"directive": "...", "params": {...}}
            ]
        }
        """

        # --------------------------------
        # Validacija workflow strukture
        # --------------------------------
        if not workflow or "steps" not in workflow:
            return {
                "workflow_executed": False,
                "error": "invalid_workflow_structure"
            }

        steps = workflow.get("steps", [])
        results: List[Dict[str, Any]] = []

        # --------------------------------
        # Izvršavanje svakog koraka
        # --------------------------------
        for index, step in enumerate(steps):
            directive = step.get("directive")
            params = step.get("params", {})

            if not directive:
                results.append({
                    "step": index,
                    "executed": False,
                    "error": "missing_directive"
                })
                continue

            try:
                result = self.executor.execute(directive, params)
            except Exception as e:
                results.append({
                    "step": index,
                    "executed": False,
                    "error": "execution_error",
                    "message": str(e),
                })
                continue

            results.append({
                "step": index,
                "executed": result.get("executed", False),
                "directive": directive,
                "result": result
            })

        return {
            "workflow_executed": True,
            "steps_results": results
        }
