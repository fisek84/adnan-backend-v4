"""
ACTION WORKFLOW SERVICE — CANONICAL (FAZA 4)

Uloga:
- izvršava DEFINISANI workflow plan
- NE donosi odluke
- NE radi governance
- NE bira agente
- NE shape-a UX response
- koristi postojeće execution servise

CANON (nakon ustava):
- Primarni i podržani put: SOP execution plan ("type": "sop_execution").
- Legacy "workflow" tip je onemogućen (ne izvršava akcije, ne zove LLM).
"""

from typing import Dict, Any

from services.sop_execution_manager import SOPExecutionManager


class ActionWorkflowService:
    """
    Workflow execution adapter.
    """

    def __init__(self):
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
        # LEGACY WORKFLOW (ONEMOGUĆEN)
        # --------------------------------------------------------
        if workflow_type == "workflow":
            # Ne pokušavamo da izvršimo korake, ne zovemo LLM niti ActionExecutionService.
            # Jasno vraćamo da je ovaj put ugašen u korist canonical
            # approval-based Notion Ops Executor-a.
            return {
                "success": False,
                "workflow_type": "workflow",
                "confirmed": False,
                "error": "legacy_workflow_disabled",
                "message": (
                    "Workflow type 'workflow' je legacy i onemogućen. "
                    "Koristi SOP execution plan ('type': 'sop_execution') i "
                    "canonical write path (approval-based Notion Ops Executor)."
                ),
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
        # Ostavljeno radi backward kompatibilnosti signatura,
        # iako se više ne koristi u canonical putu.
        return {
            "step": step,
            "executed": False,
            "confirmed": False,
            "error": error,
        }
