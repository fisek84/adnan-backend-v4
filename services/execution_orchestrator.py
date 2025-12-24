from __future__ import annotations

import logging
from typing import Any, Dict, List, Union

from models.ai_command import AICommand
from services.execution_governance_service import ExecutionGovernanceService
from services.execution_registry import ExecutionRegistry
from services.notion_ops_agent import NotionOpsAgent
from services.notion_service import get_notion_service

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ExecutionOrchestrator:
    """
    CANONICAL EXECUTION ORCHESTRATOR

    - orchestrira lifecycle
    - NE odlučuje policy
    - NE izvršava write direktno (uvijek preko agenata)
    - radi ISKLJUČIVO nad AICommand, uz ulaznu normalizaciju
    """

    def __init__(self):
        self.governance = ExecutionGovernanceService()
        self.registry = ExecutionRegistry()
        self.notion_agent = NotionOpsAgent(get_notion_service())

    async def execute(
        self, command: Union[AICommand, Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Ulaz može biti AICommand ili dict (npr. direktno iz API sloja).
        CANON: ovdje se payload kanonizuje u AICommand, bez interpretacije intent-a.
        """
        cmd = self._normalize_command(command)

        execution_id = getattr(cmd, "execution_id", None)
        if not isinstance(execution_id, str) or not execution_id:
            raise ValueError("AICommand.execution_id is required")

        directive = getattr(cmd, "command", None)
        if not isinstance(directive, str) or not directive:
            # NEMA "unknown" — audit mora imati smislen ključ
            raise ValueError("AICommand.command is required")

        # 1) REGISTER (idempotent)
        self.registry.register(cmd)

        # 2) GOVERNANCE (FIRST-PASS ONLY)
        initiator = getattr(cmd, "initiator", None)
        if not isinstance(initiator, str) or not initiator:
            initiator = "unknown"

        # context_type: field -> metadata.context_type -> directive fallback
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
        Resume nakon eksplicitnog odobrenja:
        - ne radi novi governance pass
        - koristi već registrirani AICommand
        """
        command = self.registry.get(execution_id)
        if not command:
            raise RuntimeError("Execution not found")

        # Defanzivno: ako je historijski ostao dict, kanonizuj i osvježi registry
        cmd = self._normalize_command(command)
        if cmd is not command:
            self.registry.register(cmd)

        logger.info("Resuming approved execution %s", execution_id)

        return await self._execute_after_approval(cmd)

    async def _execute_after_approval(self, command: AICommand) -> Dict[str, Any]:
        execution_id = command.execution_id

        # 4) EXECUTE (AGENT / WORKFLOW)
        command.execution_state = "EXECUTING"

        if command.command == "goal_task_workflow":
            params = command.params if isinstance(command.params, dict) else {}
            workflow_type = params.get("workflow_type")

            # Specijalni workflow: KPI WEEKLY SUMMARY → AI SUMMARY DB
            if workflow_type == "kpi_weekly_summary":
                result = await self._execute_kpi_weekly_summary_workflow(command)
            else:
                # Default: GOAL + TASK workflow
                result = await self._execute_goal_with_tasks_workflow(command)
        else:
            # Svi ostali idu direktno u NotionOpsAgent (npr. goal_write, notion_write, ...)
            result = await self.notion_agent.execute(command)

        # 5) COMPLETE
        command.execution_state = "COMPLETED"
        self.registry.complete(execution_id, result)

        return {
            "execution_id": execution_id,
            "execution_state": "COMPLETED",
            "result": result,
        }

    async def _execute_goal_with_tasks_workflow(
        self, command: AICommand
    ) -> Dict[str, Any]:
        """
        WORKFLOW:
        - kreira Goal u Goals DB
        - kreira jedan ili više Taskova u Tasks DB
        - automatski ih veže relation-om "Goal" na kreirani Goal

        Ovdje NEMA dodatnog governance passa — top-level goal_task_workflow je već odobren.
        Sve write operacije idu kroz NotionOpsAgent → NotionService.
        """
        params = command.params if isinstance(command.params, dict) else {}
        goal_spec = params.get("goal") or {}
        tasks_specs_raw = params.get("tasks") or []
        tasks_specs: List[Dict[str, Any]] = (
            tasks_specs_raw if isinstance(tasks_specs_raw, list) else []
        )

        # ---------------------------
        # 1) KREIRAJ GOAL
        # ---------------------------
        goal_cmd = AICommand(
            command="notion_write",
            intent="create_page",
            read_only=False,
            params={
                "db_key": goal_spec.get("db_key", "goals"),
                "property_specs": goal_spec.get("property_specs") or {},
            },
            initiator=command.initiator,
            owner="system",
            executor="notion_agent",
            validated=True,
            metadata={
                "context_type": "workflow",
                "workflow": "goal_task_workflow",
                "step": "create_goal",
            },
        )

        goal_result = await self.notion_agent.execute(goal_cmd)
        goal_page_id = (
            goal_result.get("notion_page_id") if isinstance(goal_result, dict) else None
        )

        # ---------------------------
        # 2) KREIRAJ TASKOVE POVEZANE NA TAJ GOAL
        # ---------------------------
        created_tasks: List[Dict[str, Any]] = []

        for t in tasks_specs:
            if not isinstance(t, dict):
                continue

            base_specs_raw = t.get("property_specs") or {}
            base_specs: Dict[str, Any] = (
                dict(base_specs_raw) if isinstance(base_specs_raw, dict) else {}
            )

            # Automatski enforce-amo relation "Goal" na kreirani goal
            if isinstance(goal_page_id, str) and goal_page_id:
                base_specs["Goal"] = {
                    "type": "relation",
                    "page_ids": [goal_page_id],
                }

            task_cmd = AICommand(
                command="notion_write",
                intent="create_page",
                read_only=False,
                params={
                    "db_key": t.get("db_key", "tasks"),
                    "property_specs": base_specs,
                },
                initiator=command.initiator,
                owner="system",
                executor="notion_agent",
                validated=True,
                metadata={
                    "context_type": "workflow",
                    "workflow": "goal_task_workflow",
                    "step": "create_task",
                },
            )

            task_result = await self.notion_agent.execute(task_cmd)
            if isinstance(task_result, dict):
                created_tasks.append(task_result)

        return {
            "success": True,
            "workflow": "goal_task_workflow",
            "goal": goal_result,
            "tasks": created_tasks,
        }

    async def _execute_kpi_weekly_summary_workflow(
        self, command: AICommand
    ) -> Dict[str, Any]:
        """
        WORKFLOW: KPI WEEKLY SUMMARY → AI SUMMARY DB

        Koraci (sve preko NotionOpsAgent-a, bez direktnog pisanja u Notion ovdje):
        1) query KPI DB za traženi time_scope (this_week / last_week, ...)
        2) NotionOpsAgent / AI generiše sažetak (3–5 rečenica) iz KPI podataka
        3) kreira se nova stranica u AI SUMMARY DB
        """
        params = command.params if isinstance(command.params, dict) else {}
        db_key = params.get("db_key", "kpi")
        time_scope = params.get("time_scope", "this_week")

        # ---------------------------
        # 1) QUERY KPI DB
        # ---------------------------
        kpi_query_cmd = AICommand(
            command="notion_write",
            intent="query_database",
            read_only=True,
            params={
                "db_key": db_key,
                "property_specs": {},
            },
            initiator=command.initiator,
            owner="system",
            executor="notion_agent",
            validated=True,
            metadata={
                "context_type": "workflow",
                "workflow": "kpi_weekly_summary",
                "step": "query_kpi",
                "report_type": "kpi_weekly_summary",
                "time_scope": time_scope,
            },
        )

        kpi_result = await self.notion_agent.execute(kpi_query_cmd)

        summary_text = None
        if isinstance(kpi_result, dict):
            summary_text = (
                kpi_result.get("summary")
                or kpi_result.get("ai_summary")
                or kpi_result.get("text")
            )

        if not isinstance(summary_text, str) or not summary_text:
            summary_text = f"Weekly KPI summary for {time_scope} generated by system."

        # ---------------------------
        # 2) UPIS U AI SUMMARY DB
        # ---------------------------
        title = f"Weekly KPI summary – {time_scope}"

        ai_summary_cmd = AICommand(
            command="notion_write",
            intent="create_page",
            read_only=False,
            params={
                "db_key": "ai_summary",
                "property_specs": {
                    "Name": {"type": "title", "text": title},
                    "Summary": {"type": "rich_text", "text": summary_text},
                },
            },
            initiator=command.initiator,
            owner="system",
            executor="notion_agent",
            validated=True,
            metadata={
                "context_type": "workflow",
                "workflow": "kpi_weekly_summary",
                "step": "write_ai_summary",
                "time_scope": time_scope,
            },
        )

        ai_summary_result = await self.notion_agent.execute(ai_summary_cmd)

        return {
            "success": True,
            "workflow": "kpi_weekly_summary",
            "time_scope": time_scope,
            "kpi_source": kpi_result,
            "ai_summary": ai_summary_result,
        }

    @staticmethod
    def _allowed_fields() -> set[str]:
        model_fields = getattr(AICommand, "model_fields", None)
        if isinstance(model_fields, dict):
            return set(model_fields.keys())

        v1_fields = getattr(AICommand, "__fields__", None)
        if isinstance(v1_fields, dict):
            return set(v1_fields.keys())

        return set()

    @staticmethod
    def _normalize_command(raw: Union[AICommand, Dict[str, Any]]) -> AICommand:
        """
        Jedini dozvoljeni kanonski tip unutar Orchestratora je AICommand.

        Ako dođe dict:
        - podrži "directive" varijantu
        - rasklopi ugniježđeni "command" dict
        - propagiraj intent
        - context_type čuvaj u metadata.context_type (ako AICommand nema field)
        - odbaci polja koja AICommand ne poznaje
        """
        if isinstance(raw, AICommand):
            return raw

        if not isinstance(raw, dict):
            raise TypeError("ExecutionOrchestrator requires AICommand or dict payload")

        data: Dict[str, Any] = dict(raw)
        allowed_fields = ExecutionOrchestrator._allowed_fields()

        # --- top-level directive support ---
        if "command" not in data:
            directive = data.get("directive")
            if isinstance(directive, str) and directive:
                data["command"] = directive

        # --- top-level context_type -> metadata fallback ---
        top_ctx = data.get("context_type")
        if isinstance(top_ctx, str) and top_ctx:
            if not allowed_fields or "context_type" not in allowed_fields:
                meta = data.get("metadata")
                if not isinstance(meta, dict):
                    meta = {}
                meta.setdefault("context_type", top_ctx)
                data["metadata"] = meta
                data.pop("context_type", None)

        # --- nested command dict support ---
        inner_cmd = data.get("command")
        if isinstance(inner_cmd, dict):
            inner_command = inner_cmd.get("command") or inner_cmd.get("directive")
            if isinstance(inner_command, str) and inner_command:
                data["command"] = inner_command

            if "params" in inner_cmd and "params" not in data:
                data["params"] = inner_cmd.get("params")

            if "intent" in inner_cmd and "intent" not in data:
                data["intent"] = inner_cmd.get("intent")

            inner_ctx = inner_cmd.get("context_type")
            if isinstance(inner_ctx, str) and inner_ctx:
                if not allowed_fields or "context_type" not in allowed_fields:
                    meta = data.get("metadata")
                    if not isinstance(meta, dict):
                        meta = {}
                    meta.setdefault("context_type", inner_ctx)
                    data["metadata"] = meta
                else:
                    data.setdefault("context_type", inner_ctx)

        if allowed_fields:
            filtered = {k: v for k, v in data.items() if k in allowed_fields}
        else:
            filtered = data

        return AICommand(**filtered)
