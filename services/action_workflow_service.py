"""
ACTION WORKFLOW SERVICE — CANONICAL (FAZA 4)

Uloga:
- izvršava DEFINISANI workflow plan
- NE donosi odluke
- NE radi governance
- NE bira agente
- NE shape-a UX response
- koristi postojeće execution servise
"""

from typing import Dict, Any, List

from services.action_execution_service import ActionExecutionService
from services.sop_execution_manager import SOPExecutionManager


class ActionWorkflowService:
    """
    Workflow execution adapter.
    """

    def __init__(self):
        self._action_executor = ActionExecutionService()
        self._sop_executor = SOPExecutionManager()

    # ============================================================
    # PUBLIC ENTRYPOINT
    # ============================================================
    async def execute_workflow(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """
        Podržani workflow formati:

        1) SOP execution plan (KANONSKI):
        {
            "type": "sop_execution",
            "execution_plan": [...]
        }

        2) Legacy workflow (DEPRECATED, READ-COMPAT):
        {
            "type": "workflow",
            "steps": [
                {"directive": "...", "params": {...}}
            ]
        }
        """

        if not workflow or "type" not in workflow:
            return self._fail("invalid_workflow_structure")

        workflow_type = workflow.get("type")

        # --------------------------------------------------------
        # SOP EXECUTION (PRIMARY PATH)
        # --------------------------------------------------------
        if workflow_type == "sop_execution":
            execution_plan = workflow.get("execution_plan")
            if not execution_plan:
                return self._fail("missing_execution_plan")

            result = await self._sop_executor.execute_plan(execution_plan)

            return {
                "success": bool(result.get("success")),
                "workflow_type": "sop_execution",
                "confirmed": bool(result.get("success")),
                "result": result,
            }

        # --------------------------------------------------------
        # LEGACY WORKFLOW (STEP-BY-STEP)
        # --------------------------------------------------------
        if workflow_type == "workflow":
            steps = workflow.get("steps", [])
            step_results: List[Dict[str, Any]] = []

            for index, step in enumerate(steps):
                directive = step.get("directive")
                params = step.get("params", {})

                if not directive:
                    step_results.append(self._step_fail(index, "missing_directive"))
                    break

                result = self._action_executor.execute(directive, params)

                step_results.append(
                    {
                        "step": index,
                        "directive": directive,
                        "executed": bool(result.get("executed")),
                        "confirmed": bool(result.get("confirmed")),
                        "result": result,
                    }
                )

                if not result.get("confirmed"):
                    break

            return {
                "success": True,
                "workflow_type": "workflow",
                "confirmed": any(r.get("confirmed") for r in step_results),
                "steps": step_results,
            }

        # --------------------------------------------------------
        # UNKNOWN
        # --------------------------------------------------------
        return self._fail(f"unsupported_workflow_type:{workflow_type}")

    # ============================================================
    # INTERNAL HELPERS
    # ============================================================
    def _fail(self, error: str) -> Dict[str, Any]:
        return {
            "success": False,
            "confirmed": False,
            "error": error,
        }

    def _step_fail(self, step: int, error: str) -> Dict[str, Any]:
        return {
            "step": step,
            "executed": False,
            "confirmed": False,
            "error": error,
        }
