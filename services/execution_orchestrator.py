from __future__ import annotations

import logging
from typing import Any, Dict, List, Union

from models.ai_command import AICommand
from services.approval_state_service import get_approval_state
from services.execution_governance_service import ExecutionGovernanceService
from services.execution_registry import get_execution_registry
from services.notion_ops_agent import NotionOpsAgent
from services.notion_service import get_notion_service

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# CANON: meta/proposal wrapper intents must never be executed/resumed
PROPOSAL_WRAPPER_INTENT = "ceo.command.propose"


class ExecutionOrchestrator:
    """
    CANONICAL EXECUTION ORCHESTRATOR

    - orkestrira lifecycle
    - NE odlučuje policy (to radi ExecutionGovernanceService + PolicyService)
    - NE izvršava write direktno (uvijek preko agenata)
    - radi ISKLJUČIVO nad AICommand, uz ulaznu normalizaciju
    """

    def __init__(self) -> None:
        self.governance = ExecutionGovernanceService()
        self.registry = get_execution_registry()
        self.notion_agent = NotionOpsAgent(get_notion_service())
        self.approvals = get_approval_state()

    def set_approvals(self, approvals: Any) -> None:
        """
        Optional injection to avoid singleton mismatch between router/gateway and orchestrator.
        """
        if approvals is not None:
            self.approvals = approvals

    @staticmethod
    def _is_proposal_wrapper(cmd: AICommand) -> bool:
        directive = getattr(cmd, "command", None)
        intent = getattr(cmd, "intent", None)
        return (directive == PROPOSAL_WRAPPER_INTENT) or (
            intent == PROPOSAL_WRAPPER_INTENT
        )

    @staticmethod
    def _is_failure_result(result: Any) -> bool:
        """
        Minimal canonical failure detection:
        - if result is dict and explicitly says ok==False or success==False, treat as failure.
        """
        if not isinstance(result, dict):
            return False
        if result.get("ok") is False:
            return True
        if result.get("success") is False:
            return True
        return False

    async def execute(
        self, command: Union[AICommand, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Ulaz može biti AICommand ili dict (npr. direktno iz API sloja).
        CANON: ovdje se payload kanonizuje u AICommand, bez interpretacije intent-a.
        """
        cmd = self._normalize_command(command)

        # DEFENSE-IN-DEPTH (CANON):
        if self._is_proposal_wrapper(cmd):
            raise ValueError(
                "proposal intent cannot be executed; unwrap/translation required before creating or resuming execution"
            )

        execution_id = getattr(cmd, "execution_id", None)
        if not isinstance(execution_id, str) or not execution_id:
            raise ValueError("AICommand.execution_id is required")

        directive = getattr(cmd, "command", None)
        if not isinstance(directive, str) or not directive:
            raise ValueError("AICommand.command is required")

        # 1) REGISTER
        self.registry.register(cmd)

        # 2) GOVERNANCE
        initiator = getattr(cmd, "initiator", None)
        if not isinstance(initiator, str) or not initiator:
            initiator = "unknown"

        context_type = getattr(cmd, "context_type", None)
        metadata = getattr(cmd, "metadata", None)

        if not isinstance(context_type, str) or not context_type:
            if isinstance(metadata, dict):
                meta_ct = metadata.get("context_type")
                if isinstance(meta_ct, str) and meta_ct:
                    context_type = meta_ct

        if not isinstance(context_type, str) or not context_type:
            context_type = directive

        params = getattr(cmd, "params", None)
        params_dict: Dict[str, Any] = params if isinstance(params, dict) else {}

        approval_id = getattr(cmd, "approval_id", None)
        if not isinstance(approval_id, str) or not approval_id:
            approval_id = None

        decision = self.governance.evaluate(
            initiator=initiator,
            context_type=context_type,
            directive=directive,
            params=params_dict,
            execution_id=execution_id,
            approval_id=approval_id,
        )

        # 3) APPROVAL GATE
        if not bool(decision.get("allowed", False)):
            decision_approval_id = decision.get("approval_id")
            if isinstance(decision_approval_id, str) and decision_approval_id:
                try:
                    cmd.approval_id = decision_approval_id
                except Exception:
                    pass

                md = getattr(cmd, "metadata", None)
                if not isinstance(md, dict):
                    md = {}
                md["approval_id"] = decision_approval_id
                cmd.metadata = md

            cmd.execution_state = "BLOCKED"
            self.registry.block(execution_id, decision)

            return {
                "execution_id": execution_id,
                "execution_state": "BLOCKED",
                "reason": decision.get("reason"),
                "approval_id": decision.get("approval_id"),
            }

        return await self._execute_after_approval(cmd)

    async def resume(self, execution_id: str) -> Dict[str, Any]:
        """
        Resume nakon eksplicitnog odobrenja.
        """
        command = self.registry.get(execution_id)
        if not command:
            raise KeyError(execution_id)

        cmd = self._normalize_command(command)
        if cmd is not command:
            self.registry.register(cmd)

        if self._is_proposal_wrapper(cmd):
            raise ValueError(
                "proposal intent cannot be resumed; unwrap/translation required before creating execution/approval"
            )

        approval_id = getattr(cmd, "approval_id", None)
        if not isinstance(approval_id, str) or not approval_id:
            md = getattr(cmd, "metadata", None)
            if isinstance(md, dict):
                meta_aid = md.get("approval_id")
                if isinstance(meta_aid, str) and meta_aid:
                    approval_id = meta_aid

        if not isinstance(approval_id, str) or not approval_id:
            return {
                "execution_id": execution_id,
                "execution_state": "BLOCKED",
                "reason": "missing_approval_id_for_resume",
            }

        if self.approvals.is_fully_approved(approval_id) is not True:
            return {
                "execution_id": execution_id,
                "execution_state": "BLOCKED",
                "reason": "approval_not_granted",
                "approval_id": approval_id,
            }

        logger.info(
            "Resuming approved execution %s (approval_id=%s)",
            execution_id,
            approval_id,
        )

        return await self._execute_after_approval(cmd)

    async def _execute_after_approval(self, command: AICommand) -> Dict[str, Any]:
        execution_id = command.execution_id

        if self._is_proposal_wrapper(command):
            raise ValueError(
                "proposal intent reached _execute_after_approval; unwrap required (bug: wrapper leaked into execution)"
            )

        command.execution_state = "EXECUTING"
        self.registry.register(command)

        try:
            if (
                getattr(command, "command", None) == "ceo_console.next_step"
                or getattr(command, "intent", None) == "ceo_console.next_step"
            ):
                result = {
                    "status": "NOOP",
                    "message": "ceo_console.next_step executed (no side effects)",
                    "params": command.params
                    if isinstance(command.params, dict)
                    else {},
                }

                command.execution_state = "COMPLETED"
                self.registry.complete(execution_id, result)

                return {
                    "execution_id": execution_id,
                    "execution_state": "COMPLETED",
                    "result": result,
                }

            if command.command == "goal_task_workflow":
                params = command.params if isinstance(command.params, dict) else {}
                workflow_type = params.get("workflow_type")

                if workflow_type == "kpi_weekly_summary":
                    result = await self._execute_kpi_weekly_summary_workflow(command)
                else:
                    result = await self._execute_goal_with_tasks_workflow(command)
            else:
                result = await self.notion_agent.execute(command)

            # ✅ FAILURE DETECTION (explicit only)
            if self._is_failure_result(result):
                failure = {
                    "reason": result.get("reason")
                    or result.get("message")
                    or "Execution failed (explicit ok/success=false).",
                    "result": result,
                }
                command.execution_state = "FAILED"
                self.registry.fail(execution_id, failure)
                return {
                    "execution_id": execution_id,
                    "execution_state": "FAILED",
                    "failure": failure,
                }

            command.execution_state = "COMPLETED"
            self.registry.complete(execution_id, result)

            return {
                "execution_id": execution_id,
                "execution_state": "COMPLETED",
                "result": result,
            }

        except Exception as exc:
            logger.exception("Execution failed execution_id=%s", execution_id)
            failure = {
                "reason": str(exc),
                "error_type": exc.__class__.__name__,
            }
            command.execution_state = "FAILED"
            self.registry.fail(execution_id, failure)
            return {
                "execution_id": execution_id,
                "execution_state": "FAILED",
                "failure": failure,
            }

    async def _execute_goal_with_tasks_workflow(
        self, command: AICommand
    ) -> Dict[str, Any]:
        params = command.params if isinstance(command.params, dict) else {}
        tasks_specs_raw = params.get("tasks") or []
        tasks_specs: List[Dict[str, Any]] = (
            tasks_specs_raw if isinstance(tasks_specs_raw, list) else []
        )

        parent_approval_id = getattr(command, "approval_id", None)
        if not isinstance(parent_approval_id, str) or not parent_approval_id:
            md = getattr(command, "metadata", None)
            if isinstance(md, dict):
                meta_aid = md.get("approval_id")
                if isinstance(meta_aid, str) and meta_aid:
                    parent_approval_id = meta_aid

        goal_result = await self.notion_agent.execute(command)
        goal_page_id = (
            goal_result.get("notion_page_id") if isinstance(goal_result, dict) else None
        )

        created_tasks: List[Dict[str, Any]] = []

        for t in tasks_specs:
            if not isinstance(t, dict):
                continue

            base_specs = dict(t.get("property_specs") or {})
            if isinstance(goal_page_id, str) and goal_page_id:
                base_specs["Goal"] = {"type": "relation", "page_ids": [goal_page_id]}

            task_cmd = AICommand(
                command="notion_write",
                intent="create_page",
                read_only=False,
                params={
                    "db_key": t.get("db_key", "tasks"),
                    "property_specs": base_specs,
                },
                initiator=command.initiator,
                validated=True,
                metadata={
                    "context_type": "workflow",
                    "workflow": "goal_task_workflow",
                    "approval_id": parent_approval_id,
                    "trace_parent": command.execution_id,
                },
            )

            tr = await self.notion_agent.execute(task_cmd)
            created_tasks.append(tr)

        return {
            "success": True,
            "workflow": "goal_task_workflow",
            "goal": goal_result,
            "tasks": created_tasks,
        }

    async def _execute_kpi_weekly_summary_workflow(
        self, command: AICommand
    ) -> Dict[str, Any]:
        params = command.params if isinstance(command.params, dict) else {}
        time_scope = params.get("time_scope", "this_week")

        summary_text = f"KPI weekly summary ({time_scope})."

        ai_summary_cmd = AICommand(
            command="notion_write",
            intent="create_page",
            read_only=False,
            params={
                "db_key": "ai_summary",
                "property_specs": {
                    "Name": {"type": "title", "text": f"KPI summary {time_scope}"},
                    "Summary": {"type": "rich_text", "text": summary_text},
                },
            },
            initiator=command.initiator,
            validated=True,
            metadata={
                "context_type": "workflow",
                "workflow": "kpi_weekly_summary",
                "approval_id": command.approval_id,
                "trace_parent": command.execution_id,
            },
        )

        result = await self.notion_agent.execute(ai_summary_cmd)
        return {"success": True, "ai_summary": result}

    @staticmethod
    def _allowed_fields() -> set[str]:
        model_fields = getattr(AICommand, "model_fields", None)
        if isinstance(model_fields, dict):
            return set(model_fields.keys())

        v1_fields = getattr(AICommand, "__fields__", None)
        if isinstance(v1_fields, dict):
            return set(v1_fields.keys())

        return set()

    @classmethod
    def _filter_kwargs(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            return {}
        allowed = cls._allowed_fields()
        if not allowed:
            return payload
        return {k: v for k, v in payload.items() if k in allowed}

    @staticmethod
    def _normalize_command(raw: Union[AICommand, Dict[str, Any]]) -> AICommand:
        if isinstance(raw, AICommand):
            return raw

        if not isinstance(raw, dict):
            raise TypeError("ExecutionOrchestrator requires AICommand or dict")

        data: Dict[str, Any] = dict(raw)
        allowed_fields = ExecutionOrchestrator._allowed_fields()

        if "command" not in data and isinstance(data.get("directive"), str):
            data["command"] = data.get("directive")

        if isinstance(data.get("command"), dict):
            inner = data["command"]
            data["command"] = inner.get("command") or inner.get("directive")
            data.setdefault("params", inner.get("params"))
            data.setdefault("intent", inner.get("intent"))

        if allowed_fields:
            data = {k: v for k, v in data.items() if k in allowed_fields}

        return AICommand(**data)
