# services/orchestrator/orchestrator_service.py

from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, Optional

from services.approval_flow import require_approval_or_block
from services.queue.queue_service import Job, QueueService

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class OrchestratorService:
    """
    ORCHESTRATOR SERVICE (Queue worker)

    Uloga:
    - prima jobove (submit/enqueue)
    - deterministički dispatch po job_type
    - prije bilo kakvog side-effect: require_approval_or_block()

    Canon:
    - Ovdje se NE kreira approval; samo se verifikuje.
    - approval_id se očekuje u job.payload ili u payload.command ili u njihovim metadata.
    """

    def __init__(self, queue: QueueService) -> None:
        self.queue = queue

        # Optional executor (ako postoji u projektu)
        self._action_executor = None
        try:
            from services.action_execution_service import (  # type: ignore
                ActionExecutionService,
            )

            self._action_executor = ActionExecutionService()
        except Exception:
            self._action_executor = None

    async def submit(
        self,
        *,
        job_type: str,
        payload: Dict[str, Any],
        execution_id: Optional[str] = None,
        max_attempts: int = 1,
    ) -> Job:
        return await self.queue.enqueue(
            job_type=job_type,
            payload=payload,
            execution_id=execution_id,
            max_attempts=max_attempts,
        )

    async def process_once(
        self, *, timeout_seconds: float = 1.0
    ) -> Optional[Dict[str, Any]]:
        """
        Obradi jedan job (ako postoji). Vraća result dict ili None (nema posla).
        """
        job = await self.queue.claim(timeout_seconds=timeout_seconds)
        if not job:
            return None

        try:
            result = await self._dispatch(job)
            if not isinstance(result, dict):
                result = {"ok": True, "result": result}
            await self.queue.ack(job.job_id, result)
            return result

        except PermissionError as e:
            # Expected path for unapproved actions — do not spam traceback
            msg = str(e)
            logger.warning(
                "Job blocked (approval gate) job_id=%s type=%s error=%s",
                job.job_id,
                job.job_type,
                msg,
            )
            await self.queue.nack(job.job_id, msg)
            return {"ok": False, "error": msg, "blocked": True}

        except Exception as e:  # noqa: BLE001
            err = repr(e)
            logger.exception(
                "Job failed job_id=%s type=%s error=%s",
                job.job_id,
                job.job_type,
                err,
            )
            await self.queue.nack(job.job_id, err)
            return {"ok": False, "error": err}

    async def _dispatch(self, job: Job) -> Dict[str, Any]:
        if job.job_type == "agent_execute":
            return await self._handle_agent_execute(job)

        raise ValueError(f"Unknown job_type: {job.job_type}")

    @staticmethod
    def _coalesce_approval_id(payload: Dict[str, Any]) -> Optional[str]:
        """
        SSOT extraction: vrati approval_id iz prvog validnog mjesta:

        - payload["approval_id"]
        - payload["metadata"]["approval_id"]
        - payload["command"]["approval_id"]
        - payload["command"]["metadata"]["approval_id"]

        Vraća None ako ništa nije nađeno ili je prazno.
        """
        # 1) payload.approval_id
        v = payload.get("approval_id")
        if isinstance(v, str) and v.strip():
            return v.strip()

        # 2) payload.metadata.approval_id
        md = payload.get("metadata")
        if isinstance(md, dict):
            v = md.get("approval_id")
            if isinstance(v, str) and v.strip():
                return v.strip()

        # 3) payload.command.approval_id
        cmd = payload.get("command")
        if isinstance(cmd, dict):
            v = cmd.get("approval_id")
            if isinstance(v, str) and v.strip():
                return v.strip()

            # 4) payload.command.metadata.approval_id
            cmd_md = cmd.get("metadata")
            if isinstance(cmd_md, dict):
                v = cmd_md.get("approval_id")
                if isinstance(v, str) and v.strip():
                    return v.strip()

        return None

    @classmethod
    def _extract_approval_context(cls, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        Context shape za services.approval_flow:

        approval_flow.check_approval() očekuje context["approval_id"] (flat).
        Zato ovdje uvijek vraćamo: {"approval_id": "..."} kad postoji.
        """
        ctx: Dict[str, Any] = {}
        approval_id = cls._coalesce_approval_id(payload)
        if approval_id:
            ctx["approval_id"] = approval_id
        return ctx

    async def _handle_agent_execute(self, job: Job) -> Dict[str, Any]:
        payload = job.payload if isinstance(job.payload, dict) else {}
        cmd = payload.get("command")
        if not isinstance(cmd, dict):
            raise ValueError("agent_execute requires payload.command (dict)")

        command_id = str(cmd.get("id") or "agent_execute")
        command_type = str(cmd.get("type") or "agent_execute")

        # HARD GATE: prije side-effect
        approval_ctx = self._extract_approval_context(payload)
        require_approval_or_block(
            command_id=command_id,
            command_type=command_type,
            context=approval_ctx,
        )

        # Izvršenje: best-effort (zavisi od ActionExecutionService API-ja)
        if self._action_executor is None:
            raise RuntimeError(
                "ActionExecutionService not available (cannot execute agent_execute)"
            )

        for meth in ("execute", "run", "dispatch"):
            fn = getattr(self._action_executor, meth, None)
            if fn and callable(fn):
                out = fn(cmd)
                if inspect.isawaitable(out):
                    out = await out
                if isinstance(out, dict):
                    return out
                return {"ok": True, "result": out}

        raise RuntimeError(
            "ActionExecutionService has no compatible execute/run/dispatch method"
        )
