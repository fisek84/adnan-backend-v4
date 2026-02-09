from __future__ import annotations

import asyncio
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
