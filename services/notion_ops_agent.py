# services/notion_ops_agent.py

from typing import Dict, Any, List
import logging

from models.ai_command import AICommand
from services.notion_service import NotionService

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class NotionOpsAgent:
    """
    NOTION OPS AGENT — CANONICAL WRITE EXECUTOR

    Pravila:
    - jedini agent koji pokreće write
    - NE gradi payload za pojedinačne Notion API pozive (to radi NotionService)
    - za workflow komande (npr. goal_task_workflow) orkestrira više NotionService poziva
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

        # WORKFLOW: GOAL + TASK(s) (uključuje i 7day mode)
        if command.command == "goal_task_workflow":
            return await self._execute_goal_task_workflow(command)

        # SVE OSTALO → direktno NotionService (create_page, update_page, query_database, create_goal, ...)
        return await self.notion.execute(command)

    async def _execute_goal_task_workflow(self, command: AICommand) -> Dict[str, Any]:
        """
        Workflow:
        - kreira Goal u odgovarajućem DB
        - kreira 1..N Taskova u Tasks DB
        - automatski veže svaki Task na Goal (relation 'Goal'), ako već nije dat
        - podržava params.mode (npr. "7day") ali ga ne interpretira semantički — to je posao NL/COO sloja
        """
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

        # ------------------------------------------
        # 1) KREIRAJ GOAL (preko NotionService)
        # ------------------------------------------
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

        # ------------------------------------------
        # 2) KREIRAJ TASK(S) + AUTO RELATION NA GOAL
        # ------------------------------------------
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

            # Ako Goal relation nije eksplicitno dat, auto-dodaj relation "Goal" → goal_page_id
            if goal_page_id and isinstance(prop_specs, dict):
                goal_relation = prop_specs.get("Goal")
                if not goal_relation:
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
