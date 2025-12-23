from __future__ import annotations

import asyncio
import time
from typing import Any, Dict, Optional

from services.queue.queue_service import QueueService, Job
from services.memory_service import MemoryService
from services.write_gateway.write_gateway import WriteGateway
from services.agent_router.agent_router import AgentRouter


class OrchestratorService:
    """
    ORCHESTRATOR SSOT (Level 1): in-process worker that claims queue jobs and executes them.
    """

    def __init__(
        self,
        *,
        queue: Optional[QueueService] = None,
        memory: Optional[MemoryService] = None,
        agent_router: Optional[AgentRouter] = None,
        write_gateway: Optional[WriteGateway] = None,
        poll_timeout_seconds: float = 1.0,
    ) -> None:
        self.queue = queue or QueueService()
        self.memory = memory or MemoryService()
        self.agent_router = agent_router or AgentRouter()
        self.write_gateway = write_gateway or WriteGateway()

        self._poll_timeout = float(poll_timeout_seconds)
        self._stop = asyncio.Event()
        self._worker_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        if self._worker_task and not self._worker_task.done():
            return
        self._stop.clear()
        self._worker_task = asyncio.create_task(
            self._worker_loop(), name="orchestrator_worker"
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except Exception:
                pass

    async def submit(
        self,
        *,
        job_type: str,
        payload: Dict[str, Any],
        execution_id: Optional[str] = None,
        max_attempts: int = 1,
        wait: bool = False,
        wait_timeout_seconds: float = 30.0,
    ) -> Dict[str, Any]:
        job = await self.queue.enqueue(
            job_type=job_type,
            payload=payload,
            execution_id=execution_id,
            max_attempts=max_attempts,
        )

        resp: Dict[str, Any] = {
            "ok": True,
            "job_id": job.job_id,
            "execution_id": job.execution_id,
            "status": job.status,
            "queued": True,
        }

        if not wait:
            return resp

        deadline = time.time() + float(wait_timeout_seconds)
        while time.time() < deadline:
            current = await self.queue.get_job(job.job_id)
            if not current:
                return {"ok": False, "reason": "job_not_found", "job_id": job.job_id}

            if current.status in ("succeeded", "failed", "cancelled"):
                return {
                    "ok": current.status == "succeeded",
                    "job_id": current.job_id,
                    "execution_id": current.execution_id,
                    "status": current.status,
                    "result": current.result,
                    "error": current.last_error,
                }

            await asyncio.sleep(0.15)

        return {
            "ok": False,
            "job_id": job.job_id,
            "execution_id": job.execution_id,
            "status": "processing",
            "reason": "timeout_waiting_for_result",
        }

    async def _worker_loop(self) -> None:
        while not self._stop.is_set():
            job = await self.queue.claim(timeout_seconds=self._poll_timeout)
            if job is None:
                continue

            try:
                result = await self._execute_job(job)
                await self.queue.ack(job.job_id, result)

                # Memory append-only outcome (Phase 4 SSOT)
                self.memory.store_decision_outcome(
                    decision_type="execution",
                    context_type="system",
                    target=job.job_type,
                    success=True,
                    metadata={
                        "job_id": job.job_id,
                        "execution_id": job.execution_id,
                        "result_summary": self._summarize(result),
                    },
                )

            except Exception as e:
                err = f"{type(e).__name__}:{str(e)}"
                await self.queue.nack(job.job_id, err)

                self.memory.store_decision_outcome(
                    decision_type="execution",
                    context_type="system",
                    target=job.job_type,
                    success=False,
                    metadata={
                        "job_id": job.job_id,
                        "execution_id": job.execution_id,
                        "error": err,
                    },
                )

    async def _execute_job(self, job: Job) -> Dict[str, Any]:
        # -----------------------------
        # AGENT JOB
        # -----------------------------
        if job.job_type == "agent_execute":
            cmd = job.payload.get("command")
            if not cmd:
                raise ValueError("agent_execute requires payload.command")

            return await self.agent_router.execute(
                {
                    "command": cmd,
                    "payload": job.payload.get("payload", {}) or {},
                    "execution_id": job.execution_id,
                }
            )

        # -----------------------------
        # WRITE JOB (via WriteGateway)
        # -----------------------------
        if job.job_type == "write_execute":
            # expects payload already in WriteGateway envelope shape
            envelope = dict(job.payload or {})
            envelope.setdefault("execution_id", job.execution_id)
            return await self.write_gateway.write(envelope)

        raise ValueError(f"unknown_job_type:{job.job_type}")

    def _summarize(self, result: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(result, dict):
            return {"type": str(type(result))}
        keys = list(result.keys())
        return {"keys": keys[:20]}
