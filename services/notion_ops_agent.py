from typing import Dict, Any, List
import logging

from models.ai_command import AICommand
from services.notion_service import NotionService
from services.weekly_memory_service import get_weekly_memory_service

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class NotionOpsAgent:
    """
    NOTION OPS AGENT — CANONICAL WRITE EXECUTOR

    - jedini agent koji izvršava write prema Notionu
    - NE gradi raw Notion API payload (radi NotionService)
    - za workflow komande (npr. goal_task_workflow, KPI weekly summary)
      orkestrira više NotionService poziva
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

        # WORKFLOW: GOAL + TASK(s)
        if command.command == "goal_task_workflow":
            return await self._execute_goal_task_workflow(command)

        # WORKFLOW: KPI WEEKLY SUMMARY
        if (
            command.command == "notion_write"
            and command.intent == "query_database"
            and (command.metadata or {}).get("report_type") == "kpi_weekly_summary"
        ):
            return await self._execute_kpi_weekly_summary(command)

        # SVE OSTALO → direktno NotionService
        return await self.notion.execute(command)

    # -------------------------------------------------
    # KPI WEEKLY SUMMARY WORKFLOW
    # -------------------------------------------------
    async def _execute_kpi_weekly_summary(self, command: AICommand) -> Dict[str, Any]:
        """
        Workflow:
        1) pozove postojeći NotionService query za KPI DB (NE diramo filter logiku)
        2) iz zadnjeg zapisa izvuče osnovne info (title, period, brojčane metrike)
        3) upiše JEDAN red u AI SUMMARY DB (db_key='ai_summary') – Name + Summary
        4) upiše zadnji sažetak u WeeklyMemoryService za CEO dashboard
        """
        meta = command.metadata or {}

        # 1) originalni query koji je već prolazio happy path
        logger.info(
            "NotionOpsAgent KPI weekly summary: delegating KPI query to NotionService"
        )
        kpi_query_result = await self.notion.execute(command)

        results: List[Dict[str, Any]] = kpi_query_result.get("results") or []
        latest = results[-1] if results else None

        period_label = None
        kpi_title = None
        metrics: Dict[str, Any] = {}

        if latest and isinstance(latest, dict):
            props = latest.get("properties") or {}

            # title iz KPI page-a
            kpi_title = self._extract_title(props)

            # pokušaj izvući date iz property-ja "Period" (ako postoji)
            period_prop = props.get("Period") or {}
            if isinstance(period_prop, dict):
                date = period_prop.get("date") or {}
                if isinstance(date, dict):
                    period_label = date.get("start") or None

            metrics = self._extract_numeric_metrics(props)

        # 2) sastavimo kratki tekstni rezime
        if not results:
            summary_core = "nema KPI zapisa u bazi za traženi period"
        else:
            parts: List[str] = []
            if period_label:
                parts.append(f"period {period_label}")
            if metrics:
                metrics_str = ", ".join(f"{k}={v}" for k, v in metrics.items())
                parts.append(f"metrike: {metrics_str}")
            if kpi_title:
                parts.append(f"glavni zapis: '{kpi_title}'")

            summary_core = (
                "; ".join(parts) if parts else "KPI podaci su uspješno pročitani"
            )

        name_text = f"Weekly KPI summary – {summary_core}"
        summary_text = summary_core  # ide u Notion 'Summary' polje

        # 3) upišemo zapis u AI SUMMARY DB (Name + Summary)
        summary_cmd = AICommand(
            command="notion_write",
            intent="create_page",
            read_only=False,
            params={
                "db_key": "ai_summary",  # mapirano na NOTION_AI_SUMMARY_DB_ID u NotionService
                "property_specs": {
                    "Name": {
                        "type": "title",
                        "text": name_text,
                    },
                    "Summary": {
                        "type": "rich_text",
                        "text": summary_text,
                    },
                },
            },
            metadata={
                "context_type": "system",
                "source": meta.get("source") or "kpi_weekly_summary",
                "time_scope": meta.get("time_scope"),
            },
            validated=True,
        )

        logger.info(
            "NotionOpsAgent KPI weekly summary: creating AI summary page (title='%s')",
            name_text,
        )

        try:
            summary_page = await self.notion.execute(summary_cmd)
        except Exception as e:
            logger.exception("Failed to create AI summary page: %s", e)
            summary_page = {"error": str(e)}

        # 4) upišemo u WeeklyMemoryService da CEO dashboard ima šta prikazati
        summary_page_safe = summary_page if isinstance(summary_page, dict) else {}
        wm_payload: Dict[str, Any] = {
            "title": kpi_title or "AI Weekly KPI summary",
            "week_range": meta.get("time_scope") or "Ova sedmica",
            "short_summary": summary_core,
            "notion_page_id": summary_page_safe.get("notion_page_id"),
            # NotionService tipično vraća 'notion_url' ili 'url'
            "notion_url": summary_page_safe.get("notion_url")
            or summary_page_safe.get("url"),
        }

        get_weekly_memory_service().set_latest_ai_summary(wm_payload)

        return {
            "success": True,
            "workflow": "kpi_weekly_summary",
            "kpi_query": kpi_query_result,
            "summary_page": summary_page,
        }

    # -------------------------------------------------
    # HELPERS
    # -------------------------------------------------
    @staticmethod
    def _extract_title(props: Dict[str, Any]) -> str | None:
        """
        Pokušava izvući plain-text title iz Notion properties (Name ili bilo koji title).
        """
        if not isinstance(props, dict):
            return None

        candidates = []
        if "Name" in props:
            candidates.append(props["Name"])

        for value in props.values():
            if isinstance(value, dict) and value.get("type") == "title":
                candidates.append(value)

        for prop in candidates:
            if not isinstance(prop, dict):
                continue
            title_arr = prop.get("title") or []
            for item in title_arr:
                if not isinstance(item, dict):
                    continue
                plain = item.get("plain_text")
                if plain:
                    return plain
                text = item.get("text") or {}
                if isinstance(text, dict):
                    content = text.get("content")
                    if content:
                        return content

        return None

    @staticmethod
    def _extract_numeric_metrics(props: Dict[str, Any]) -> Dict[str, Any]:
        """
        Generički izvuče sve 'number' property-jeve kao KPI metrike.
        """
        metrics: Dict[str, Any] = {}
        if not isinstance(props, dict):
            return metrics

        for name, prop in props.items():
            if not isinstance(prop, dict):
                continue
            if prop.get("type") != "number":
                continue
            value = prop.get("number")
            if value is None:
                continue
            metrics[name] = value

        return metrics

    # -------------------------------------------------
    # GOAL + TASK WORKFLOW (postojeći)
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
