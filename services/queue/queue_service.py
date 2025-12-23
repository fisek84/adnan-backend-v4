from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, Optional, Literal, List


JobStatus = Literal["queued", "processing", "succeeded", "failed", "cancelled"]


@dataclass
class Job:
    job_id: str
    job_type: str
    payload: Dict[str, Any]
    execution_id: str
    created_at_unix: float
    status: JobStatus = "queued"
    attempts: int = 0
    max_attempts: int = 1
    last_error: Optional[str] = None
    result: Optional[Dict[str, Any]] = None


class QueueService:
    """
    QUEUE SSOT (Level 1): in-memory asyncio queue, deterministic idempotency by execution_id.
    """

    def __init__(self) -> None:
        self._q: asyncio.Queue[str] = asyncio.Queue()
        self._jobs: Dict[str, Job] = {}
        self._execution_index: Dict[str, str] = {}  # execution_id -> job_id
        self._lock = asyncio.Lock()

    async def enqueue(
        self,
        *,
        job_type: str,
        payload: Dict[str, Any],
        execution_id: Optional[str] = None,
        max_attempts: int = 1,
    ) -> Job:
        if not job_type:
            raise ValueError("job_type is required")
        if not isinstance(payload, dict):
            raise ValueError("payload must be a dict")

        exec_id = execution_id or f"exec_{uuid.uuid4().hex}"

        async with self._lock:
            # idempotency: if execution_id already exists, return existing job
            existing_id = self._execution_index.get(exec_id)
            if existing_id and existing_id in self._jobs:
                return self._jobs[existing_id]

            job_id = str(uuid.uuid4())
            job = Job(
                job_id=job_id,
                job_type=job_type,
                payload=payload,
                execution_id=exec_id,
                created_at_unix=time.time(),
                status="queued",
                attempts=0,
                max_attempts=max(1, int(max_attempts)),
            )
            self._jobs[job_id] = job
            self._execution_index[exec_id] = job_id

            await self._q.put(job_id)
            return job

    async def claim(self, *, timeout_seconds: float = 1.0) -> Optional[Job]:
        try:
            job_id = await asyncio.wait_for(self._q.get(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            return None

        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None

            if job.status != "queued":
                return None

            job.status = "processing"
            job.attempts += 1
            return job

    async def ack(self, job_id: str, result: Dict[str, Any]) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = "succeeded"
            job.result = result
            job.last_error = None

    async def nack(self, job_id: str, error: str) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return

            job.last_error = error

            if job.attempts < job.max_attempts:
                job.status = "queued"
                await self._q.put(job_id)
                return

            job.status = "failed"

    async def cancel(self, job_id: str) -> None:
        async with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return
            job.status = "cancelled"

    async def get_job(self, job_id: str) -> Optional[Job]:
        async with self._lock:
            return self._jobs.get(job_id)

    async def get_job_by_execution_id(self, execution_id: str) -> Optional[Job]:
        async with self._lock:
            job_id = self._execution_index.get(execution_id)
            return self._jobs.get(job_id) if job_id else None

    async def snapshot(self, limit: int = 200) -> List[Dict[str, Any]]:
        async with self._lock:
            jobs = list(self._jobs.values())[-max(1, int(limit)) :]
            return [
                {
                    "job_id": j.job_id,
                    "job_type": j.job_type,
                    "execution_id": j.execution_id,
                    "status": j.status,
                    "attempts": j.attempts,
                    "max_attempts": j.max_attempts,
                    "created_at_unix": j.created_at_unix,
                    "last_error": j.last_error,
                }
                for j in jobs
            ]
