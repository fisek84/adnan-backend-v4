# services/execution_orchestrator.py

from __future__ import annotations

import logging
from typing import Any, Dict, List, Union

from models.ai_command import AICommand
from services.approval_state_service import get_approval_state
from services.execution_governance_service import ExecutionGovernanceService
from services.execution_registry import ExecutionRegistry
from services.notion_ops_agent import NotionOpsAgent
from services.notion_service import get_notion_service

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


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
        self.registry = ExecutionRegistry()
        self.notion_agent = NotionOpsAgent(get_notion_service())
        self.approvals = get_approval_state()

    async def execute(self, command: Union[AICommand, Dict[str, Any]]) -> Dict[str, Any]:
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
            # Persist approval_id onto the registered command so resume() hard-gate can pass deterministically.
            decision_approval_id = decision.get("approval_id")
            if isinstance(decision_approval_id, str) and decision_approval_id:
                try:
                    cmd.approval_id = decision_approval_id  # type: ignore[attr-defined]
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

        # ------------------------------------------------------------
        # HARD APPROVAL GATE (FAZA 1)
        # ------------------------------------------------------------
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

    async def _execute_goal_with_tasks_workflow(self, command: AICommand) -> Dict[str, Any]:
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
        tasks_specs: List[Dict[str, Any]] = tasks_specs_raw if isinstance(tasks_specs_raw, list) else []

        parent_approval_id = getattr(command, "approval_id", None)
        if not isinstance(parent_approval_id, str) or not parent_approval_id:
            md = getattr(command, "metadata", None)
            if isinstance(md, dict):
                meta_aid = md.get("approval_id")
                if isinstance(meta_aid, str) and meta_aid:
                    parent_approval_id = meta_aid
            if not isinstance(parent_approval_id, str) or not parent_approval_id:
                parent_approval_id = None

        allowed_fields = self._allowed_fields()

        # ---------------------------
        # 1) KREIRAJ GOAL
        # ---------------------------
        goal_metadata: Dict[str, Any] = {
            "context_type": "workflow",
            "workflow": "goal_task_workflow",
            "step": "create_goal",
            "trace_parent": command.execution_id,
        }
        if parent_approval_id:
            goal_metadata["approval_id"] = parent_approval_id

        goal_kwargs: Dict[str, Any] = {
            "command": "notion_write",
            "intent": "create_page",
            "read_only": False,
            "params": {
                "db_key": (goal_spec.get("db_key") if isinstance(goal_spec, dict) else None) or "goals",
                "property_specs": (goal_spec.get("property_specs") if isinstance(goal_spec, dict) else None) or {},
            },
            "initiator": command.initiator,
            "owner": "system",
            "executor": "notion_agent",
            "validated": True,
            "metadata": goal_metadata,
        }
        if "execution_id" in allowed_fields:
            goal_kwargs["execution_id"] = command.execution_id
        if parent_approval_id and "approval_id" in allowed_fields:
            goal_kwargs["approval_id"] = parent_approval_id

        goal_cmd = AICommand(**self._filter_kwargs(goal_kwargs))
        goal_result = await self.notion_agent.execute(goal_cmd)
        goal_page_id = goal_result.get("notion_page_id") if isinstance(goal_result, dict) else None

        # ---------------------------
        # 2) KREIRAJ TASKOVE POVEZANE NA TAJ GOAL
        # ---------------------------
        created_tasks: List[Dict[str, Any]] = []

        for t in tasks_specs:
            if not isinstance(t, dict):
                continue

            base_specs_raw = t.get("property_specs") or {}
            base_specs: Dict[str, Any] = dict(base_specs_raw) if isinstance(base_specs_raw, dict) else {}

            # Automatski enforce-amo relation "Goal" na kreirani goal
            if isinstance(goal_page_id, str) and goal_page_id:
                base_specs["Goal"] = {"type": "relation", "page_ids": [goal_page_id]}

            task_metadata: Dict[str, Any] = {
                "context_type": "workflow",
                "workflow": "goal_task_workflow",
                "step": "create_task",
                "trace_parent": command.execution_id,
            }
            if parent_approval_id:
                task_metadata["approval_id"] = parent_approval_id

            task_kwargs: Dict[str, Any] = {
                "command": "notion_write",
                "intent": "create_page",
                "read_only": False,
                "params": {
                    "db_key": t.get("db_key", "tasks"),
                    "property_specs": base_specs,
                },
                "initiator": command.initiator,
                "owner": "system",
                "executor": "notion_agent",
                "validated": True,
                "metadata": task_metadata,
            }
            if "execution_id" in allowed_fields:
                task_kwargs["execution_id"] = command.execution_id
            if parent_approval_id and "approval_id" in allowed_fields:
                task_kwargs["approval_id"] = parent_approval_id

            task_cmd = AICommand(**self._filter_kwargs(task_kwargs))
            task_result = await self.notion_agent.execute(task_cmd)
            if isinstance(task_result, dict):
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

        Kanonski tok:
        1) query KPI DB (read-only) preko NotionOpsAgent → NotionService
        2) ORCHESTRATOR ovdje deterministički napravi sažetak iz results
        3) upiše novu stranicu u AI SUMMARY DB
        """
        params = command.params if isinstance(command.params, dict) else {}
        db_key = params.get("db_key", "kpi")
        time_scope = params.get("time_scope", "this_week")

        parent_approval_id = getattr(command, "approval_id", None)
        if not isinstance(parent_approval_id, str) or not parent_approval_id:
            md = getattr(command, "metadata", None)
            if isinstance(md, dict):
                meta_aid = md.get("approval_id")
                if isinstance(meta_aid, str) and meta_aid:
                    parent_approval_id = meta_aid
            if not isinstance(parent_approval_id, str) or not parent_approval_id:
                parent_approval_id = None

        allowed_fields = self._allowed_fields()

        # ---------------------------
        # 1) QUERY KPI DB
        # ---------------------------
        kpi_meta: Dict[str, Any] = {
            "context_type": "workflow",
            "workflow": "kpi_weekly_summary",
            "step": "query_kpi",
            "time_scope": time_scope,
            "trace_parent": command.execution_id,
        }
        if parent_approval_id:
            kpi_meta["approval_id"] = parent_approval_id

        kpi_kwargs: Dict[str, Any] = {
            "command": "notion_write",
            "intent": "query_database",
            "read_only": True,
            "params": {
                "db_key": db_key,
                "property_specs": {},
            },
            "initiator": command.initiator,
            "owner": "system",
            "executor": "notion_agent",
            "validated": True,
            "metadata": kpi_meta,
        }
        if "execution_id" in allowed_fields:
            kpi_kwargs["execution_id"] = command.execution_id
        if parent_approval_id and "approval_id" in allowed_fields:
            kpi_kwargs["approval_id"] = parent_approval_id

        kpi_query_cmd = AICommand(**self._filter_kwargs(kpi_kwargs))
        kpi_result = await self.notion_agent.execute(kpi_query_cmd)

        results = []
        if isinstance(kpi_result, dict):
            results = kpi_result.get("results") or []
        if not isinstance(results, list):
            results = []

        # ---------------------------
        # 2) BUILD SUMMARY (deterministički)
        # ---------------------------
        summary_text = self._build_kpi_summary_text(results, time_scope=time_scope)

        # ---------------------------
        # 3) WRITE AI SUMMARY DB
        # ---------------------------
        title = f"Weekly KPI summary – {time_scope}"

        ai_meta: Dict[str, Any] = {
            "context_type": "workflow",
            "workflow": "kpi_weekly_summary",
            "step": "write_ai_summary",
            "time_scope": time_scope,
            "trace_parent": command.execution_id,
        }
        if parent_approval_id:
            ai_meta["approval_id"] = parent_approval_id

        ai_kwargs: Dict[str, Any] = {
            "command": "notion_write",
            "intent": "create_page",
            "read_only": False,
            "params": {
                "db_key": "ai_summary",
                "property_specs": {
                    "Name": {"type": "title", "text": title},
                    "Summary": {"type": "rich_text", "text": summary_text},
                },
            },
            "initiator": command.initiator,
            "owner": "system",
            "executor": "notion_agent",
            "validated": True,
            "metadata": ai_meta,
        }
        if "execution_id" in allowed_fields:
            ai_kwargs["execution_id"] = command.execution_id
        if parent_approval_id and "approval_id" in allowed_fields:
            ai_kwargs["approval_id"] = parent_approval_id

        ai_summary_cmd = AICommand(**self._filter_kwargs(ai_kwargs))
        ai_summary_result = await self.notion_agent.execute(ai_summary_cmd)

        return {
            "success": True,
            "workflow": "kpi_weekly_summary",
            "time_scope": time_scope,
            "kpi_source": kpi_result,
            "ai_summary": ai_summary_result,
        }

    @staticmethod
    def _build_kpi_summary_text(results: List[Any], *, time_scope: str) -> str:
        """
        Minimalan deterministički sažetak:
        - uzme zadnji KPI zapis (ako postoji)
        - izvuče title (Name) i sve number property-jeve
        - vrati 1–3 rečenice
        """
        if not results:
            return f"Nema KPI zapisa za period '{time_scope}'."

        latest = results[-1]
        if not isinstance(latest, dict):
            return f"KPI zapisi su pronađeni za '{time_scope}', ali format zapisa nije očekivan."

        props = latest.get("properties") or {}
        if not isinstance(props, dict):
            props = {}

        # title
        title = None
        name_prop = props.get("Name")
        if isinstance(name_prop, dict) and name_prop.get("type") == "title":
            title_arr = name_prop.get("title") or []
            if isinstance(title_arr, list):
                pieces = [p.get("plain_text", "") for p in title_arr if isinstance(p, dict)]
                title = "".join(pieces).strip() or None

        # numbers
        metrics: Dict[str, Any] = {}
        for k, v in props.items():
            if not isinstance(v, dict):
                continue
            if v.get("type") != "number":
                continue
            n = v.get("number")
            if n is None:
                continue
            metrics[k] = n

        metrics_str = ""
        if metrics:
            items = list(metrics.items())[:12]
            metrics_str = ", ".join(f"{k}={v}" for k, v in items)

        if title and metrics_str:
            return f"Period '{time_scope}': '{title}'. Metrike: {metrics_str}."
        if title:
            return f"Period '{time_scope}': '{title}'."
        if metrics_str:
            return f"Period '{time_scope}': Metrike: {metrics_str}."
        return f"Period '{time_scope}': KPI zapisi su pronađeni."

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
        """
        Safety: AICommand je često strict (extra=forbid). Ovo filtrira kwargs na stvarno postojeća polja.
        Ako se polja ne mogu introspektovati, vraća payload kako jeste (legacy behavior).
        """
        if not isinstance(payload, dict):
            return {}
        allowed = cls._allowed_fields()
        if not allowed:
            return payload
        return {k: v for k, v in payload.items() if k in allowed}

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
