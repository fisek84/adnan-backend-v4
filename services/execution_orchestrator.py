# C:\adnan-backend-v4\services\execution_orchestrator.py

from typing import Dict, Any
import logging

from services.sop_execution_manager import SOPExecutionManager
from services.notion_ops.ops_engine import NotionOpsEngine

logger = logging.getLogger(__name__)


class ExecutionOrchestrator:
    """
    Action Workflow Orchestrator

    RESPONSIBILITIES:
    - Route execution to correct agent
    - Execute workflow
    - Support dry-run simulation
    - Return raw execution result
    - NO decisions
    - NO CSI changes
    """

    def __init__(self):
        self._sop_executor = SOPExecutionManager()
        self._notion_executor = NotionOpsEngine()

    async def execute(
        self,
        decision: Dict[str, Any],
        *,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        """
        Execute or simulate delegated action.

        decision MUST contain:
        - executor
        - command
        - payload
        """

        executor = decision.get("executor")
        command = decision.get("command")
        payload = decision.get("payload", {})

        if not executor or not command:
            return {
                "success": False,
                "summary": "Nema izvršne akcije.",
            }

        # --------------------------------------------------
        # DRY-RUN (SIMULATION MODE)
        # --------------------------------------------------
        if dry_run:
            logger.info("DRY-RUN → %s | %s", executor, command)
            return {
                "success": True,
                "dry_run": True,
                "executor": executor,
                "command": command,
                "payload": payload,
                "summary": "Simulacija izvršenja (bez ikakve akcije).",
            }

        logger.info("EXEC → %s | %s", executor, command)

        # --------------------------------------------------
        # SOP EXECUTION
        # --------------------------------------------------
        if executor == "sop_execution_manager":
            execution_plan = payload.get("execution_plan")
            sop_id = payload.get("sop_id")

            if not execution_plan:
                return {
                    "success": False,
                    "summary": "Nedostaje SOP execution plan.",
                }

            return await self._sop_executor.execute_plan(
                execution_plan=execution_plan,
                current_sop=sop_id,
            )

        # --------------------------------------------------
        # NOTION OPS
        # --------------------------------------------------
        if executor == "notion_ops":
            return await self._notion_executor.execute(
                command=command,
                payload=payload,
            )

        # --------------------------------------------------
        # UNKNOWN EXECUTOR
        # --------------------------------------------------
        return {
            "success": False,
            "summary": f"Nepoznat executor: {executor}",
        }
