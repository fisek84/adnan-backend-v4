# services/action_workflow_service.py

"""
Workflow Execution Engine — FAZA 4 (KANONSKI)

Uloge:
- Prepoznaje klasični workflow
- Prepoznaje SOP execution plan
- Delegira SOP na SOPExecutionManager
- Ne donosi odluke
"""

from typing import Dict, Any, List

from services.action_execution_service import ActionExecutionService
from services.sop_execution_manager import SOPExecutionManager


class ActionWorkflowService:
    def __init__(self):
        self.executor = ActionExecutionService()
        self.sop_executor = SOPExecutionManager()

    # ============================================================
    # PUBLIC ENTRYPOINT
    # ============================================================
    async def execute_workflow(self, workflow: Dict[str, Any]) -> Dict[str, Any]:
        """
        Podržani formati:

        1) Legacy workflow:
        {
            "type": "workflow",
            "steps": [
                {"directive": "...", "params": {...}}
            ]
        }

        2) SOP execution plan:
        {
            "type": "sop_execution",
            "execution_plan": [
                {
                    "step": 1,
                    "agent": "notion_ops",
                    "command": "...",
                    "payload": {...}
                }
            ]
        }
        """

        if not workflow or "type" not in workflow:
            return {
                "success": False,
                "error": "invalid_workflow_structure",
            }

        workflow_type = workflow.get("type")

        # --------------------------------------------------------
        # SOP WORKFLOW (FAZA 4)
        # --------------------------------------------------------
        if workflow_type == "sop_execution":
            execution_plan = workflow.get("execution_plan")

            if not execution_plan:
                return {
                    "success": False,
                    "error": "missing_execution_plan",
                }

            return await self.sop_executor.execute_plan(execution_plan)

        # --------------------------------------------------------
        # LEGACY WORKFLOW (ZADRŽANO)
        # --------------------------------------------------------
        if workflow_type == "workflow":
            steps = workflow.get("steps", [])
            results: List[Dict[str, Any]] = []

            for index, step in enumerate(steps):
                directive = step.get("directive")
                params = step.get("params", {})

                if not directive:
                    results.append({
                        "step": index,
                        "executed": False,
                        "error": "missing_directive",
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
                    "result": result,
                })

            return {
                "success": True,
                "workflow_executed": True,
                "steps_results": results,
            }

        # --------------------------------------------------------
        # UNKNOWN
        # --------------------------------------------------------
        return {
            "success": False,
            "error": f"unsupported_workflow_type: {workflow_type}",
        }
