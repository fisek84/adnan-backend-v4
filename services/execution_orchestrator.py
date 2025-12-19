from typing import Dict, Any, Union, List
import logging

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

    async def execute(self, command: Union[AICommand, Dict[str, Any]]) -> Dict[str, Any]:
        """
        Ulaz može biti AICommand ili dict (npr. direktno iz API sloja).
        CANON: ovdje se payload kanonizuje u AICommand, bez interpretacije intent-a.
        """
        cmd = self._normalize_command(command)
        execution_id = cmd.execution_id

        # 1) REGISTER (idempotent)
        self.registry.register(cmd)

        # 2) GOVERNANCE (FIRST-PASS ONLY)
        decision = self.governance.evaluate(
            initiator=cmd.initiator,
            context_type=cmd.command,
            directive=cmd.command,
            params=cmd.params or {},
            execution_id=execution_id,
            approval_id=cmd.approval_id,
        )

        # 3) APPROVAL GATE
        if not decision.get("allowed"):
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
            params = command.params or {}
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

    async def _execute_goal_with_tasks_workflow(self, command: AICommand) -> Dict[str, Any]:
        """
        WORKFLOW:
        - kreira Goal u Goals DB
        - kreira jedan ili više Taskova u Tasks DB
        - automatski ih veže relation-om "Goal" na kreirani Goal

        Ovdje NEMA dodatnog governance passa — top-level goal_task_workflow je već odobren.
        Sve write operacije idu kroz NotionOpsAgent → NotionService.
        """
        params = command.params or {}
        goal_spec = params.get("goal") or {}
        tasks_specs: List[Dict[str, Any]] = params.get("tasks") or []

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
        goal_page_id = goal_result.get("notion_page_id")

        # ---------------------------
        # 2) KREIRAJ TASKOVE POVEZANE NA TAJ GOAL
        # ---------------------------
        created_tasks = []

        for t in tasks_specs:
            base_specs = dict(t.get("property_specs") or {})

            # Automatski enforce-amo relation "Goal" na kreirani goal
            if goal_page_id:
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
            created_tasks.append(task_result)

        return {
            "success": True,
            "workflow": "goal_task_workflow",
            "goal": goal_result,
            "tasks": created_tasks,
        }

    async def _execute_kpi_weekly_summary_workflow(self, command: AICommand) -> Dict[str, Any]:
        """
        WORKFLOW: KPI WEEKLY SUMMARY → AI SUMMARY DB

        Koraci (sve preko NotionOpsAgent-a, bez direktnog pisanja u Notion ovdje):
        1) query KPI DB za traženi time_scope (this_week / last_week, ...)
        2) NotionOpsAgent / AI generiše sažetak (3–5 rečenica) iz KPI podataka
        3) kreira se nova stranica u AI SUMMARY DB (vezan na NOTION_AI_SUMMARY_DB_ID)
        """
        params = command.params or {}
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

        # Pretpostavka: NotionOpsAgent / AI sloj može vratiti neki summary field
        summary_text = (
            (isinstance(kpi_result, dict) and (
                kpi_result.get("summary")
                or kpi_result.get("ai_summary")
                or kpi_result.get("text")
            ))
            or f"Weekly KPI summary for {time_scope} generated by system."
        )

        # ---------------------------
        # 2) UPIS U AI SUMMARY DB
        #    CANON: ne uvodimo nove property-je koji ne postoje u DB
        #    Minimalni siguran set: Name (title) + Summary (rich_text)
        # ---------------------------
        title = f"Weekly KPI summary – {time_scope}"

        ai_summary_cmd = AICommand(
            command="notion_write",
            intent="create_page",
            read_only=False,
            params={
                # DB key za AI Weekly / AI Summary DB
                "db_key": "ai_summary",
                "property_specs": {
                    "Name": {
                        "type": "title",
                        "text": title,
                    },
                    "Summary": {
                        "type": "rich_text",
                        "text": summary_text,
                    },
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
    def _normalize_command(raw: Union[AICommand, Dict[str, Any]]) -> AICommand:
        """
        Jedini dozvoljeni kanonski tip unutar Orchestratora je AICommand.
        Ako dođe dict, radimo istu normalizaciju kao Registry:
        - rasklapamo ugniježđeni "command" dict
        - propagiramo intent
        - odbacujemo polja koja AICommand ne poznaje
        """
        if isinstance(raw, AICommand):
            return raw

        if isinstance(raw, dict):
            data = dict(raw)

            inner_cmd = data.get("command")
            if isinstance(inner_cmd, dict):
                if "command" in inner_cmd:
                    data["command"] = inner_cmd["command"]
                if "params" in inner_cmd and "params" not in data:
                    data["params"] = inner_cmd["params"]
                if "context_type" in inner_cmd and "context_type" not in data:
                    data["context_type"] = inner_cmd["context_type"]
                if "intent" in inner_cmd and "intent" not in data:
                    data["intent"] = inner_cmd["intent"]

            allowed_fields = set(AICommand.model_fields.keys())
            filtered = {k: v for k, v in data.items() if k in allowed_fields}

            return AICommand(**filtered)

        raise TypeError("ExecutionOrchestrator requires AICommand or dict payload")
