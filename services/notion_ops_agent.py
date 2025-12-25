# services/notion_ops_agent.py

from __future__ import annotations

from typing import Dict, Any, List
import logging

from models.ai_command import AICommand
from services.notion_service import NotionService

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class NotionOpsAgent:
    """
    NOTION OPS AGENT — CANONICAL WRITE EXECUTOR

    - jedini agent koji izvršava write prema Notionu (preko NotionService)
    - NE gradi raw Notion API payload (radi NotionService)
    - NE radi KPI weekly summary workflow ovdje (to je posao Orchestratora),
      da ne dođe do duplih upisa i divergentne logike.
    """

    def __init__(self, notion: NotionService):
        self.notion = notion

    async def execute(self, command: AICommand) -> Dict[str, Any]:
        if not command.intent:
            raise RuntimeError("Write command missing intent")

        logger.info(
            "NotionOpsAgent executing cmd=%s intent=%s execution_id=%s",
            command.command,
            command.intent,
            command.execution_id,
        )

        # Legacy support: ako neko direktno pozove goal_task_workflow mimo Orchestratora.
        if command.command == "goal_task_workflow":
            return await self._execute_goal_task_workflow(command)

        # Sve ostalo → direktno NotionService
        return await self.notion.execute(command)

    # -------------------------------------------------
    # GOAL + TASK WORKFLOW (legacy; Orchestrator primarno orkestrira)
    # -------------------------------------------------
    async def _execute_goal_task_workflow(self, command: AICommand) -> Dict[str, Any]:
        params = command.params or {}

        mode: str = params.get("mode") or "default"
        goal_spec: Dict[str, Any] = params.get("goal") or {}
        tasks_specs: List[Dict[str, Any]] = params.get("tasks") or []

        if not isinstance(goal_spec, dict):
            raise RuntimeError("goal_task_workflow requires 'goal' dict in params")

        if not isinstance(tasks_specs, list) or len(tasks_specs) == 0:
            raise RuntimeError(
                "goal_task_workflow requires non-empty 'tasks' list in params"
            )

        # 1) GOAL
        goal_params: Dict[str, Any] = {
            "db_key": goal_spec.get("db_key"),
            "database_id": goal_spec.get("database_id"),
            "property_specs": goal_spec.get("property_specs"),
            "properties": goal_spec.get("properties"),
        }

        goal_cmd = AICommand(
            command="notion_write",
            intent="create_page",
            read_only=False,
            params=goal_params,
            metadata={"context_type": "system", "source": "workflow"},
            validated=True,
        )

        logger.info(
            "NotionOpsAgent workflow: creating GOAL via NotionService (db_key=%s)",
            goal_params.get("db_key"),
        )

        goal_result = await self.notion.execute(goal_cmd)
        goal_page_id = goal_result.get("notion_page_id")

        if not goal_page_id:
            raise RuntimeError(
                "goal_task_workflow: NotionService did not return notion_page_id for goal"
            )

        # 2) TASKS
        tasks_results: List[Dict[str, Any]] = []

        for idx, task_spec in enumerate(tasks_specs, start=1):
            if not isinstance(task_spec, dict):
                continue

            t_params: Dict[str, Any] = {
                "db_key": task_spec.get("db_key", "tasks"),
                "database_id": task_spec.get("database_id"),
                "property_specs": dict(task_spec.get("property_specs") or {}),
                "properties": task_spec.get("properties"),
            }

            prop_specs = t_params.get("property_specs") or {}

            # enforce relation Goal -> kreirani goal
            if goal_page_id and isinstance(prop_specs, dict):
                if not prop_specs.get("Goal"):
                    prop_specs["Goal"] = {
                        "type": "relation",
                        "page_ids": [goal_page_id],
                    }
                    t_params["property_specs"] = prop_specs

            task_cmd = AICommand(
                command="notion_write",
                intent="create_page",
                read_only=False,
                params=t_params,
                metadata={
                    "context_type": "system",
                    "source": "workflow",
                    "task_index": idx,
                },
                validated=True,
            )

            logger.info(
                "NotionOpsAgent workflow: creating TASK #%s via NotionService (db_key=%s)",
                idx,
                t_params.get("db_key"),
            )

            tr = await self.notion.execute(task_cmd)
            tasks_results.append(tr)

        return {
            "success": True,
            "workflow": "goal_task_workflow",
            "mode": mode,
            "goal": goal_result,
            "tasks": tasks_results,
        }
