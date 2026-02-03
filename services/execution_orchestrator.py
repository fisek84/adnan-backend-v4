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
from services.memory_ops_executor import MemoryOpsExecutor
from services.notion_ops_state import is_armed as notion_ops_is_armed

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
        self.memory_ops = MemoryOpsExecutor()
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
    def _is_memory_write(cmd: AICommand) -> bool:
        return cmd.command == "memory_write" or cmd.intent == "memory_write"

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

        # SSOT safety: Notion writes must never dispatch when Notion Ops is not ARMED.
        # This is session-scoped and only enforced when session_id is present.
        try:
            if cmd.intent == "notion_write" or cmd.command == "notion_write":
                md = (
                    cmd.metadata
                    if isinstance(getattr(cmd, "metadata", None), dict)
                    else {}
                )
                session_id = md.get("session_id") if isinstance(md, dict) else None
                if isinstance(session_id, str) and session_id.strip():
                    armed = await notion_ops_is_armed(session_id.strip())
                    if not armed:
                        cmd.execution_state = "BLOCKED"
                        self.registry.block(
                            cmd.execution_id,
                            {
                                "allowed": False,
                                "reason": "notion_ops_disarmed",
                                "execution_id": cmd.execution_id,
                                "approval_id": cmd.approval_id,
                                "context_type": cmd.context_type or cmd.command,
                                "directive": cmd.command,
                            },
                        )
                        return {
                            "execution_id": cmd.execution_id,
                            "execution_state": "BLOCKED",
                            "approval_id": cmd.approval_id,
                            "reason": "notion_ops_disarmed",
                        }
        except Exception:
            # Fail-soft: do not crash execution path on gating errors.
            pass

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
            # Safety net: meta next_step should never hit Notion executor.
            if (
                cmd.intent == "ceo_console.next_step"
                or cmd.command == "ceo_console.next_step"
            ):
                cmd.read_only = True
                cmd.execution_state = "COMPLETED"
                res = {
                    "ok": True,
                    "execution_state": "COMPLETED",
                    "read_only": True,
                    "result": {"message": "next_step_noop"},
                }
                self.registry.complete(cmd.execution_id, res)
                return {
                    "execution_id": cmd.execution_id,
                    "execution_state": "COMPLETED",
                    "result": res,
                }

            # ---------- READ-ONLY DIRECTIVE: refresh_snapshot ----------
            # Canon: read-only, no writes, must return deterministic non-null result.
            if (cmd.intent == "refresh_snapshot") or (
                cmd.command == "refresh_snapshot"
            ):
                cmd.read_only = True
                try:
                    from services.knowledge_snapshot_service import (
                        KnowledgeSnapshotService,
                    )  # type: ignore

                    # Invalidate all relevant process-local caches so chat/advisor cannot
                    # keep serving stale snapshots after an explicit refresh.
                    try:
                        from services.session_snapshot_cache import (
                            SESSION_SNAPSHOT_CACHE,
                        )  # type: ignore

                        SESSION_SNAPSHOT_CACHE.clear()
                    except Exception:
                        pass

                    try:
                        from services.kb_notion_store import (
                            clear_kb_notion_process_cache,
                        )  # type: ignore

                        clear_kb_notion_process_cache()
                    except Exception:
                        pass

                    try:
                        notion = get_notion_service()
                        if hasattr(notion, "clear_caches"):
                            notion.clear_caches()  # type: ignore[attr-defined]
                    except Exception:
                        pass

                    # Use the configured sync service (properly constructed in dependencies).
                    # This avoids instantiating NotionSyncService() without required args.
                    try:
                        from dependencies import get_sync_service  # type: ignore

                        sync_service = get_sync_service()
                        ok = await sync_service.sync_knowledge_snapshot()
                    except Exception as exc:
                        ok = False

                        refresh_errors = [
                            {
                                "type": exc.__class__.__name__,
                                "message": str(exc),
                            }
                        ]
                        refresh_meta = {
                            "ok": False,
                            "error": f"refresh_snapshot_sync_service_failed:{exc}",
                        }
                    else:
                        refresh_errors = (
                            getattr(sync_service, "last_refresh_errors", None)
                            if ok is False
                            else []
                        )
                        refresh_meta = (
                            getattr(sync_service, "last_refresh_meta", None)
                            if ok is False
                            else {}
                        )

                    ks = KnowledgeSnapshotService.get_snapshot()
                    snapshot_meta = {
                        "last_sync": ks.get("last_sync"),
                        "expired": bool(ks.get("expired")),
                        "ready": bool(ks.get("ready")),
                        "ttl_seconds": ks.get("ttl_seconds"),
                        "age_seconds": ks.get("age_seconds"),
                    }

                    # Unified grounding refresh meta (no IO)
                    try:
                        from dependencies import get_memory_read_only_service  # type: ignore
                        from services.grounding_pack_service import (  # type: ignore
                            GroundingPackService,
                        )

                        mem_ro = get_memory_read_only_service()
                        mem_snapshot = mem_ro.export_public_snapshot() if mem_ro else {}
                        gp = GroundingPackService.build(
                            prompt="refresh_snapshot",
                            knowledge_snapshot=ks if isinstance(ks, dict) else {},
                            memory_public_snapshot=mem_snapshot,
                            legacy_trace={"intent": "refresh_snapshot"},
                            agent_id="refresh_snapshot",
                        )
                        grounding_refresh = {
                            "enabled": bool(gp.get("enabled") is True)
                            if isinstance(gp, dict)
                            else False,
                            "generated_at": gp.get("diagnostics", {}).get(
                                "generated_at"
                            )
                            if isinstance(gp, dict)
                            else None,
                            "identity_pack_hash": gp.get("identity_pack", {}).get(
                                "hash"
                            )
                            if isinstance(gp, dict)
                            else None,
                            "kb_hash": gp.get("kb_snapshot", {}).get("hash")
                            if isinstance(gp, dict)
                            else None,
                            "memory_hash": gp.get("memory_snapshot", {}).get("hash")
                            if isinstance(gp, dict)
                            else None,
                        }
                    except Exception:
                        grounding_refresh = {"enabled": False}

                    res = {
                        "ok": bool(ok),
                        "success": bool(ok),
                        "read_only": True,
                        "intent": "refresh_snapshot",
                        "refresh_errors": refresh_errors
                        if isinstance(refresh_errors, list)
                        else [],
                        "refresh_meta": refresh_meta
                        if isinstance(refresh_meta, dict)
                        else {},
                        "snapshot_meta": snapshot_meta,
                        "knowledge_snapshot": ks,
                        "grounding_refresh": grounding_refresh,
                    }
                except Exception as exc:
                    # Even on failure, return a deterministic non-null result.
                    try:
                        from services.knowledge_snapshot_service import (
                            KnowledgeSnapshotService,
                        )  # type: ignore

                        ks = KnowledgeSnapshotService.get_snapshot()
                    except Exception:
                        ks = {"ready": False, "expired": None, "payload": {}}

                    snapshot_meta = {
                        "last_sync": ks.get("last_sync"),
                        "expired": bool(ks.get("expired"))
                        if isinstance(ks, dict)
                        else None,
                        "ready": bool(ks.get("ready"))
                        if isinstance(ks, dict)
                        else None,
                        "ttl_seconds": ks.get("ttl_seconds")
                        if isinstance(ks, dict)
                        else None,
                        "age_seconds": ks.get("age_seconds")
                        if isinstance(ks, dict)
                        else None,
                    }

                    res = {
                        "ok": False,
                        "success": False,
                        "read_only": True,
                        "intent": "refresh_snapshot",
                        "error": str(exc),
                        "error_type": exc.__class__.__name__,
                        "snapshot_meta": snapshot_meta,
                        "knowledge_snapshot": ks,
                        "grounding_refresh": {"enabled": False},
                    }

                if res.get("ok") is True:
                    cmd.execution_state = "COMPLETED"
                    self.registry.complete(cmd.execution_id, res)
                    return {
                        "execution_id": cmd.execution_id,
                        "execution_state": "COMPLETED",
                        "result": res,
                    }

                cmd.execution_state = "FAILED"
                self.registry.fail(cmd.execution_id, res)
                reason = res.get("error") or "refresh_snapshot failed"
                return {
                    "execution_id": cmd.execution_id,
                    "execution_state": "FAILED",
                    "result": res,
                    "failure": res,
                    "ok": False,
                    "text": f"Execution FAILED: {reason}",
                }

            # ---------- WORKFLOW ----------
            if self._is_goal_task_workflow(cmd):
                result = await self._execute_goal_task_workflow(cmd)
            elif self._is_memory_write(cmd):
                result = await self.memory_ops.execute(cmd)
            else:
                result = await self.notion_agent.execute(cmd)

            # memory_write is fail-soft by contract: invalid payloads still produce a
            # deterministic result object and do not escalate to FAILED envelope.
            if (
                self._is_memory_write(cmd)
                and isinstance(result, dict)
                and result.get("ok") is False
            ):
                cmd.execution_state = "COMPLETED"
                self.registry.complete(cmd.execution_id, result)
                return {
                    "execution_id": cmd.execution_id,
                    "execution_state": "COMPLETED",
                    "result": result,
                }

            if self._is_failure_result(result):
                cmd.execution_state = "FAILED"
                self.registry.fail(cmd.execution_id, result)
                # Provide a human-readable failure message for UI consumers.
                # CEO Console prefers `text` when available.
                reason = None
                if isinstance(result, dict):
                    reason = (
                        result.get("reason")
                        or result.get("message")
                        or result.get("detail")
                        or result.get("error")
                    )
                reason_str = (
                    str(reason)
                    if isinstance(reason, str) and reason.strip()
                    else "Execution failed"
                )
                return {
                    "execution_id": cmd.execution_id,
                    "execution_state": "FAILED",
                    "failure": result,
                    "ok": False,
                    "text": f"Execution FAILED: {reason_str}",
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
            reason_str = (
                str(failure.get("reason") or "Execution failed").strip()
                or "Execution failed"
            )
            return {
                "execution_id": cmd.execution_id,
                "execution_state": "FAILED",
                "failure": failure,
                "ok": False,
                "text": f"Execution FAILED: {reason_str}",
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
