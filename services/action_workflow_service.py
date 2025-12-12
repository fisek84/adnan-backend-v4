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
                "confirmed": False,
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
                    "confirmed": False,
                    "error": "missing_execution_plan",
                }

            result = await self.sop_executor.execute_plan(execution_plan)

            # SOP executor već zna outcome → samo propagacija
            return {
                **result,
                "confirmed": bool(result.get("success")),
            }

        # --------------------------------------------------------
        # LEGACY WORKFLOW (ZADRŽANO)
        # --------------------------------------------------------
        if workflow_type == "workflow":
            steps = workflow.get("steps", [])
            results: List[Dict[str, Any]] = []
            confirmed = False

            for index, step in enumerate(steps):
                directive = step.get("directive")
                params = step.get("params", {})

                if not directive:
                    results.append({
                        "step": index,
                        "executed": False,
                        "confirmed": False,
                        "error": "missing_directive",
                    })
                    continue

                try:
                    result = self.executor.execute(directive, params)
                except Exception as e:
                    results.append({
                        "step": index,
                        "executed": False,
                        "confirmed": False,
                        "error": "execution_error",
                        "message": str(e),
                    })
                    continue

                step_confirmed = bool(result.get("confirmed"))
                confirmed = confirmed or step_confirmed

                results.append({
                    "step": index,
                    "executed": result.get("executed", False),
                    "confirmed": step_confirmed,
                    "directive": directive,
                    "result": result,
                })

            return {
                "success": True,
                "workflow_executed": True,
                "confirmed": confirmed,
                "steps_results": results,
            }

        # --------------------------------------------------------
        # UNKNOWN
        # --------------------------------------------------------
        return {
            "success": False,
            "confirmed": False,
            "error": f"unsupported_workflow_type: {workflow_type}",
        }
