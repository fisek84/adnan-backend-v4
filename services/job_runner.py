from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from dataclasses import field
from typing import Any, Dict, List, Optional, Sequence
from uuid import uuid4

from models.ai_command import AICommand
from services.agent_registry_service import AgentRegistryService


def _safe_str(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def _ensure_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


@dataclass
class JobRunner:
    """In-process manual Job Runner.

    Contract:
    - Input: list of pending job dicts (tasks/goals) using an existing read path.
    - Assignment: SSOT-driven (config/agents.json role + job_contract).
    - Execution: dispatch via ExecutionOrchestrator (governance + tool runtime).
    - Handoff: emits notion_ops handoff log (existing path) after COMPLETED or BLOCKED.

    Note: This runner intentionally has no scheduler; call it manually from CLI/tests.
    """

    orchestrator: Any
    agents_json_path: str = "config/agents.json"
    max_concurrency: int = 2
    max_retries: int = 3
    backoff_base_seconds: float = 0.1
    idempotency_ttl_seconds: Optional[float] = None

    _seen_job_ids: Dict[str, float] = field(
        default_factory=dict, init=False, repr=False
    )

    _seen_step_keys: Dict[str, float] = field(
        default_factory=dict, init=False, repr=False
    )

    def _cleanup_seen(self, now: float) -> None:
        ttl = self.idempotency_ttl_seconds
        if ttl is None:
            return
        try:
            ttl_s = float(ttl)
        except Exception:
            return
        if ttl_s <= 0:
            return

        expired_before = now - ttl_s
        for job_id, ts in list(self._seen_job_ids.items()):
            if ts < expired_before:
                self._seen_job_ids.pop(job_id, None)

        for key, ts in list(self._seen_step_keys.items()):
            if ts < expired_before:
                self._seen_step_keys.pop(key, None)

    def _mark_seen(self, job_id: str) -> bool:
        job_id_norm = _safe_str(job_id)
        if not job_id_norm:
            return False

        now = time.monotonic()
        self._cleanup_seen(now)
        if job_id_norm in self._seen_job_ids:
            return True

        self._seen_job_ids[job_id_norm] = now
        return False

    def _mark_seen_step(self, key: str) -> bool:
        key_norm = _safe_str(key)
        if not key_norm:
            return False

        now = time.monotonic()
        self._cleanup_seen(now)
        if key_norm in self._seen_step_keys:
            return True
        self._seen_step_keys[key_norm] = now
        return False

    @staticmethod
    def _step_id(template_id: str, step_index: int) -> str:
        tid = _safe_str(template_id)
        n = int(step_index)
        return f"{tid}:step_{n + 1}" if tid else f"step_{n + 1}"

    @staticmethod
    def _step_execution_id(job_id: str, step_id: str) -> str:
        # Deterministic for idempotency: job_id + step_id
        jid = _safe_str(job_id)
        sid = _safe_str(step_id)
        base = f"exec_job_{jid}_{sid}" if jid and sid else f"exec_job_{jid or sid}"
        # normalize to keep execution_id filesystem-friendly
        return base.replace(":", "_").replace(" ", "_")

    @staticmethod
    def _map_step_params(
        params_schema: Dict[str, Any], inputs: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Deterministic mapping: copy only keys declared in params_schema from inputs."""
        if not isinstance(params_schema, dict) or not isinstance(inputs, dict):
            return {}

        out: Dict[str, Any] = {}
        for k in sorted(params_schema.keys()):
            if not isinstance(k, str) or not k.strip():
                continue
            if k in inputs:
                out[k] = inputs.get(k)
        return out

    @staticmethod
    def _approval_id_for_step(inputs: Dict[str, Any], step_id: str) -> str:
        if not isinstance(inputs, dict):
            return ""
        # Accept either a single approval_id (single-step templates) or a dict mapping.
        direct = _safe_str(inputs.get("approval_id"))
        if direct:
            return direct
        by_step = inputs.get("approval_ids") or inputs.get("approval_id_by_step")
        if isinstance(by_step, dict):
            return _safe_str(by_step.get(step_id))
        return ""

    def _find_existing_approval_by_execution_id(
        self,
        *,
        approvals: Any,
        execution_id: str,
        command: str,
    ) -> Optional[Dict[str, Any]]:
        try:
            all_approvals = approvals.list_approvals() if approvals is not None else []
        except Exception:
            all_approvals = []
        eid = _safe_str(execution_id)
        cmd = _safe_str(command)
        for a in all_approvals:
            if not isinstance(a, dict):
                continue
            if _safe_str(a.get("execution_id")) != eid:
                continue
            if _safe_str(a.get("command")) != cmd:
                continue
            if a.get("status") not in ("pending", "approved"):
                continue
            return dict(a)
        return None

    @staticmethod
    def _payload_key(payload_summary: Dict[str, Any]) -> str:
        try:
            return json.dumps(payload_summary or {}, sort_keys=True, default=str)
        except Exception:
            return "{}"

    async def run_template(
        self,
        template_id: str,
        inputs: Dict[str, Any],
        initiator: str,
        job_id: str,
    ) -> Dict[str, Any]:
        """Execute an SSOT job template end-to-end via approvals + existing orchestrator.

        Contract:
        - Creates approvals (scope=api_execute_raw) when required, never auto-approves.
        - When fully-approved approval_ids are supplied in inputs, executes steps.
        - Idempotent by (job_id, step_id): does not create a second approval/execution.
        """

        from services.job_templates_service import get_job_templates_service
        from services.tools_catalog_service import get_tools_catalog_service

        tid = _safe_str(template_id)
        jid = _safe_str(job_id) or f"job_{uuid4().hex}"
        initiator_norm = _safe_str(initiator) or "system"
        inputs_norm = inputs if isinstance(inputs, dict) else {}

        tools_catalog = get_tools_catalog_service()
        tools_catalog.load_from_tools_json(
            os.getenv("TOOLS_JSON_PATH") or "config/tools.json",
            clear=True,
        )

        templates = get_job_templates_service()
        templates.load_from_job_templates_json(
            tools_catalog,
            os.getenv("JOB_TEMPLATES_JSON_PATH") or "config/job_templates.json",
            clear=True,
        )

        tmpl = templates.get(tid)
        if tmpl is None:
            return {
                "ok": False,
                "execution_state": "FAILED",
                "reason": "template_not_found",
                "template_id": tid,
                "job_id": jid,
            }

        agent_id = _safe_str(
            self._resolve_dept_agent_id_for_role(getattr(tmpl, "role", "") or "") or ""
        )
        if not agent_id:
            return {
                "ok": False,
                "execution_state": "BLOCKED",
                "reason": "no_agent_for_role",
                "template_id": tid,
                "job_id": jid,
                "role": getattr(tmpl, "role", None),
            }

        approvals = getattr(self.orchestrator, "approvals", None)

        step_results: List[Dict[str, Any]] = []
        pending: List[Dict[str, Any]] = []

        for idx, step in enumerate(getattr(tmpl, "steps", []) or []):
            step_id = self._step_id(tid, idx)
            step_key = f"{jid}:{step_id}"

            tool_action = _safe_str(getattr(step, "tool_action", "") or "")
            params_schema = getattr(step, "params_schema", None)
            params_schema = params_schema if isinstance(params_schema, dict) else {}
            mapped_params = self._map_step_params(params_schema, inputs_norm)

            exec_id = self._step_execution_id(jid, step_id)
            params: Dict[str, Any] = {"action": tool_action}
            params.update(mapped_params)

            md: Dict[str, Any] = {
                "agent_id": agent_id,
                "job_runner": True,
                "job_id": jid,
                "template_id": tid,
                "step_id": step_id,
                "emit_handoff_log": False,
            }

            approval_id = self._approval_id_for_step(inputs_norm, step_id)
            requires_approval = bool(getattr(step, "requires_approval", False) is True)

            # Idempotency: prevent multiple distinct payloads for the same (job_id, step_id).
            payload_summary = {"action": tool_action, **mapped_params}
            payload_key = self._payload_key(payload_summary)
            existing = self._find_existing_approval_by_execution_id(
                approvals=approvals,
                execution_id=exec_id,
                command="tool_call",
            )
            if existing is not None:
                existing_key = _safe_str(existing.get("payload_key"))
                if existing_key and existing_key != payload_key:
                    return {
                        "ok": False,
                        "execution_state": "BLOCKED",
                        "reason": "idempotency_conflict",
                        "job_id": jid,
                        "template_id": tid,
                        "step_id": step_id,
                        "execution_id": exec_id,
                        "approval_id": existing.get("approval_id"),
                    }
                if not approval_id:
                    approval_id = _safe_str(existing.get("approval_id"))

            if requires_approval and not approval_id:
                # Create (or reuse) approval in the same shape as /api/execute/raw.
                tool = tools_catalog.get(tool_action)
                risk_level = tool.risk_level if tool is not None else "unknown"
                if approvals is None or not hasattr(approvals, "create"):
                    return {
                        "ok": False,
                        "execution_state": "FAILED",
                        "reason": "approval_service_unavailable",
                        "job_id": jid,
                        "template_id": tid,
                        "step_id": step_id,
                        "execution_id": exec_id,
                    }

                approval = approvals.create(
                    command="tool_call",
                    payload_summary=payload_summary,
                    scope="api_execute_raw",
                    risk_level=str(risk_level or "unknown"),
                    execution_id=exec_id,
                )
                approval_id = _safe_str(approval.get("approval_id"))
                if not approval_id:
                    return {
                        "ok": False,
                        "execution_state": "FAILED",
                        "reason": "approval_create_failed",
                        "job_id": jid,
                        "template_id": tid,
                        "step_id": step_id,
                        "execution_id": exec_id,
                    }

                cmd = AICommand(
                    command="tool_call",
                    intent="tool_call",
                    params=params,
                    initiator=initiator_norm,
                    execution_id=exec_id,
                    approval_id=approval_id,
                    metadata=md,
                )
                # Register for later resume.
                try:
                    self.orchestrator.registry.register(cmd)
                except Exception:
                    pass

                step_rec = {
                    "step_id": step_id,
                    "tool_action": tool_action,
                    "execution_id": exec_id,
                    "execution_state": "BLOCKED",
                    "reason": "approval_required",
                    "approval_id": approval_id,
                }
                step_results.append(step_rec)
                pending.append(step_rec)

                # Guard against double enqueue in the same process.
                self._mark_seen_step(step_key)
                continue

            # If an approval exists but is not yet fully approved, return it as pending.
            if requires_approval and approval_id:
                fully_approved = False
                try:
                    if approvals is not None and hasattr(
                        approvals, "is_fully_approved"
                    ):
                        fully_approved = bool(approvals.is_fully_approved(approval_id))
                except Exception:
                    fully_approved = False

                if fully_approved is not True:
                    cmd = AICommand(
                        command="tool_call",
                        intent="tool_call",
                        params=params,
                        initiator=initiator_norm,
                        execution_id=exec_id,
                        approval_id=approval_id,
                        metadata=md,
                    )
                    try:
                        self.orchestrator.registry.register(cmd)
                    except Exception:
                        pass

                    step_rec = {
                        "step_id": step_id,
                        "tool_action": tool_action,
                        "execution_id": exec_id,
                        "execution_state": "BLOCKED",
                        "reason": "approval_not_granted",
                        "approval_id": approval_id,
                    }
                    step_results.append(step_rec)
                    pending.append(step_rec)
                    self._mark_seen_step(step_key)
                    continue

            # If we have an approval_id, attempt execution (will BLOCK if not fully approved).
            cmd = AICommand(
                command="tool_call",
                intent="tool_call",
                params=params,
                initiator=initiator_norm,
                execution_id=exec_id,
                approval_id=approval_id,
                metadata=md,
            )
            res = await self.orchestrator.execute(cmd)
            step_results.append(
                {
                    "step_id": step_id,
                    "tool_action": tool_action,
                    "execution_id": exec_id,
                    "approval_id": approval_id,
                    "execution_state": res.get("execution_state")
                    if isinstance(res, dict)
                    else None,
                    "result": res.get("result") if isinstance(res, dict) else None,
                    "failure": res.get("failure") if isinstance(res, dict) else None,
                }
            )

            if isinstance(res, dict) and res.get("execution_state") in {
                "BLOCKED",
                "FAILED",
            }:
                # Stop on first non-success to preserve deterministic behavior.
                return {
                    "ok": False,
                    "job_id": jid,
                    "template_id": tid,
                    "agent_id": agent_id,
                    "execution_state": res.get("execution_state"),
                    "steps": step_results,
                }

        overall_state = "COMPLETED"
        if pending:
            overall_state = "BLOCKED"

        return {
            "ok": overall_state == "COMPLETED",
            "job_id": jid,
            "template_id": tid,
            "agent_id": agent_id,
            "execution_state": overall_state,
            "steps": step_results,
            "pending_approvals": [
                {
                    "step_id": p.get("step_id"),
                    "approval_id": p.get("approval_id"),
                    "execution_id": p.get("execution_id"),
                    "tool_action": p.get("tool_action"),
                }
                for p in pending
            ],
        }

    def _resolve_dept_agent_id_for_role(self, role: str) -> Optional[str]:
        role_norm = _safe_str(role).lower()
        if not role_norm:
            return None

        reg = AgentRegistryService()
        reg.load_from_agents_json(self.agents_json_path, clear=True)

        candidates = []
        for entry in reg.list_agents(enabled_only=True):
            if not isinstance(entry, object):
                continue
            if not isinstance(getattr(entry, "id", None), str):
                continue
            if not entry.id.startswith("dept_"):
                continue

            md = (
                entry.metadata
                if isinstance(getattr(entry, "metadata", None), dict)
                else {}
            )
            entry_role = md.get("role")
            if isinstance(entry_role, str) and entry_role.strip().lower() == role_norm:
                candidates.append(entry)

        if not candidates:
            return None

        # Deterministic: AgentRegistryService already sorts by priority desc then id asc.
        return candidates[0].id

    async def run_pending(self, pending: Sequence[dict]) -> List[dict]:
        semaphore = asyncio.Semaphore(
            int(self.max_concurrency) if int(self.max_concurrency) > 0 else 1
        )

        async def _run_one(job: dict) -> Optional[dict]:
            if not isinstance(job, dict):
                return None

            status = _safe_str(job.get("status") or "pending").lower()
            if status and status != "pending":
                return None

            job_id = _safe_str(job.get("id") or job.get("task_id"))
            if not job_id:
                job_id = f"job_{uuid4().hex}"

            if self._mark_seen(job_id) is True:
                return {
                    "execution_id": f"exec_job_{job_id}",
                    "execution_state": "SKIPPED",
                    "result": {
                        "skipped": True,
                        "reason": "idempotent_replay",
                        "job_id": job_id,
                    },
                }

            role = _safe_str(
                job.get("role") or job.get("dept_role") or job.get("department")
            )
            agent_id = _safe_str(job.get("agent_id"))
            if not agent_id:
                agent_id = _safe_str(self._resolve_dept_agent_id_for_role(role) or "")

            if not agent_id:
                return {
                    "execution_id": f"exec_job_{job_id}",
                    "execution_state": "BLOCKED",
                    "result": {"reason": "no_agent_for_role", "role": role},
                }

            command = _safe_str(job.get("command") or job.get("intent") or "tool_call")
            intent = _safe_str(job.get("intent") or command) or command
            params = _ensure_dict(job.get("params"))
            approval_id = _safe_str(job.get("approval_id"))
            execution_id = _safe_str(job.get("execution_id")) or f"exec_job_{job_id}"

            md = _ensure_dict(job.get("metadata"))
            md.setdefault("agent_id", agent_id)
            md.setdefault("emit_handoff_log", True)
            md.setdefault("job_runner", True)
            md.setdefault("job_id", job_id)
            if role:
                md.setdefault("role", role)

            cmd = AICommand(
                command=command,
                intent=intent,
                params=params,
                initiator=_safe_str(job.get("initiator")) or "system",
                execution_id=execution_id,
                approval_id=approval_id,
                metadata=md,
            )

            await semaphore.acquire()
            try:
                attempt = 0
                while True:
                    try:
                        res = await self.orchestrator.execute(cmd)
                        break
                    except Exception as exc:
                        if attempt >= int(self.max_retries):
                            return {
                                "execution_id": execution_id,
                                "execution_state": "FAILED",
                                "failure": {
                                    "reason": str(exc),
                                    "error_type": exc.__class__.__name__,
                                },
                            }
                        attempt += 1
                        backoff = float(self.backoff_base_seconds) * (
                            2 ** (attempt - 1)
                        )
                        await asyncio.sleep(backoff)

                result_dict = (
                    res
                    if isinstance(res, dict)
                    else {"execution_id": execution_id, "execution_state": "FAILED"}
                )

                # If the orchestrator returned BLOCKED, its built-in handoff logger was not called.
                # Reuse the existing notion_ops path by calling the orchestrator's hook directly.
                try:
                    if (
                        isinstance(res, dict)
                        and res.get("execution_state") == "BLOCKED"
                        and hasattr(self.orchestrator, "_log_handoff_completion")
                    ):
                        # Only emit handoff logs when we have a fully-approved approval_id.
                        approved = False
                        try:
                            approvals = getattr(self.orchestrator, "approvals", None)
                            if approvals is not None and hasattr(
                                approvals, "is_fully_approved"
                            ):
                                approved = bool(
                                    approvals.is_fully_approved(cmd.approval_id)
                                )
                        except Exception:
                            approved = False

                        if approved is True:
                            inner = res.get("result")
                            await self.orchestrator._log_handoff_completion(cmd, inner)
                except Exception:
                    pass

                return result_dict
            finally:
                semaphore.release()

        tasks = [asyncio.create_task(_run_one(j)) for j in list(pending or [])]
        out = await asyncio.gather(*tasks)
        return [r for r in out if isinstance(r, dict)]
