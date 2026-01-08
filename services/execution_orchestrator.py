# services/execution_orchestrator.py
# ruff: noqa: E402
from __future__ import annotations

import logging
from typing import Any, Dict, Union

from models.ai_command import AICommand
from models.canon import PROPOSAL_WRAPPER_INTENT
from services.approval_state_service import get_approval_state
from services.execution_governance_service import ExecutionGovernanceService
from services.execution_registry import get_execution_registry
from services.notion_ops_agent import NotionOpsAgent
from services.notion_service import get_notion_service

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ExecutionOrchestrator:
    """
    CANONICAL EXECUTION ORCHESTRATOR (PRODUCTION)

    HARD GUARANTEES:
    - approval_id MUST exist before ANY write
    - proposal wrappers are NEVER executable
    - goal_task_workflow is handled HERE (workflow layer)
    - NotionOpsAgent ONLY executes concrete Notion intents
    """

    def __init__(self) -> None:
        self.governance = ExecutionGovernanceService()
        self.registry = get_execution_registry()
        self.notion_agent = NotionOpsAgent(get_notion_service())
        self.approvals = get_approval_state()

    # --------------------------------------------------
    # CLASSIFIERS
    # --------------------------------------------------
    @staticmethod
    def _is_proposal_wrapper(cmd: AICommand) -> bool:
        return (
            cmd.command == PROPOSAL_WRAPPER_INTENT
            or cmd.intent == PROPOSAL_WRAPPER_INTENT
        )

    @staticmethod
    def _is_goal_task_workflow(cmd: AICommand) -> bool:
        return cmd.command == "goal_task_workflow" or cmd.intent == "goal_task_workflow"

    @staticmethod
    def _is_failure_result(result: Any) -> bool:
        return isinstance(result, dict) and (
            result.get("ok") is False or result.get("success") is False
        )

    # --------------------------------------------------
    # NORMALIZATION (SSOT)
    # --------------------------------------------------
    @staticmethod
    def _normalize_command(raw: Union[AICommand, Dict[str, Any]]) -> AICommand:
        if isinstance(raw, AICommand):
            cmd = raw
        else:
            cmd = AICommand(**raw)

        if not cmd.intent and cmd.command and cmd.command != PROPOSAL_WRAPPER_INTENT:
            cmd.intent = cmd.command

        return cmd

    # --------------------------------------------------
    # PUBLIC API
    # --------------------------------------------------
    async def execute(
        self, command: Union[AICommand, Dict[str, Any]]
    ) -> Dict[str, Any]:
        cmd = self._normalize_command(command)

        if self._is_proposal_wrapper(cmd):
            raise ValueError("proposal wrapper cannot be executed")

        self.registry.register(cmd)

        decision = self.governance.evaluate(
            initiator=cmd.initiator or "unknown",
            context_type=cmd.context_type or cmd.command,
            directive=cmd.command,
            params=cmd.params or {},
            execution_id=cmd.execution_id,
            approval_id=cmd.approval_id,
        )

        if not decision.get("allowed"):
            cmd.execution_state = "BLOCKED"
            cmd.approval_id = decision.get("approval_id")
            self.registry.block(cmd.execution_id, decision)
            return {
                "execution_id": cmd.execution_id,
                "execution_state": "BLOCKED",
                "approval_id": cmd.approval_id,
            }

        return await self._execute_after_approval(cmd)

    async def resume(self, execution_id: str) -> Dict[str, Any]:
        cmd = self.registry.get(execution_id)
        if not isinstance(cmd, AICommand):
            raise KeyError(execution_id)

        cmd = self._normalize_command(cmd)

        if not self.approvals.is_fully_approved(cmd.approval_id):
            return {
                "execution_id": execution_id,
                "execution_state": "BLOCKED",
                "approval_id": cmd.approval_id,
            }

        return await self._execute_after_approval(cmd)

    # --------------------------------------------------
    # POST-APPROVAL EXECUTION
    # --------------------------------------------------
    async def _execute_after_approval(self, cmd: AICommand) -> Dict[str, Any]:
        cmd.execution_state = "EXECUTING"
        self.registry.register(cmd)

        try:
            # ---------- WORKFLOW ----------
            if self._is_goal_task_workflow(cmd):
                result = await self._execute_goal_task_workflow(cmd)
            else:
                result = await self.notion_agent.execute(cmd)

            if self._is_failure_result(result):
                cmd.execution_state = "FAILED"
                self.registry.fail(cmd.execution_id, result)
                return {
                    "execution_id": cmd.execution_id,
                    "execution_state": "FAILED",
                    "failure": result,
                }

            cmd.execution_state = "COMPLETED"
            self.registry.complete(cmd.execution_id, result)
            return {
                "execution_id": cmd.execution_id,
                "execution_state": "COMPLETED",
                "result": result,
            }

        except Exception as exc:
            cmd.execution_state = "FAILED"
            failure = {"reason": str(exc), "error_type": exc.__class__.__name__}
            self.registry.fail(cmd.execution_id, failure)
            return {
                "execution_id": cmd.execution_id,
                "execution_state": "FAILED",
                "failure": failure,
            }

    # --------------------------------------------------
    # WORKFLOWS
    # --------------------------------------------------
    async def _execute_goal_task_workflow(self, cmd: AICommand) -> Dict[str, Any]:
        params = cmd.params or {}
        workflow = (params.get("workflow_type") or "").strip()

        if workflow == "kpi_weekly_summary":
            ns = get_notion_service()
            res = await ns.execute(
                AICommand(
                    command="query_database",
                    intent="query_database",
                    params={
                        "db_key": params.get("db_key", "kpi"),
                        "page_size": 50,
                    },
                    initiator=cmd.initiator or "system",
                    read_only=True,
                    metadata={"workflow": "kpi_weekly_summary"},
                )
            )

            items = res.get("results", []) if isinstance(res, dict) else []
            return {
                "ok": True,
                "success": True,
                "workflow_type": "kpi_weekly_summary",
                "items_count": len(items),
                "best_effort": True,
            }

        return {
            "ok": False,
            "success": False,
            "reason": f"unsupported_workflow_type:{workflow}",
        }
