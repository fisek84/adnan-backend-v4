# services/orchestrator/orchestrator_service.py

from __future__ import annotations

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

    Napomena (kompatibilnost):
    - dependencies.py (ili wiring) može proslijediti memory/agent_router/write_gateway.
      Orchestrator ih trenutno NE koristi, ali ih prihvatamo da mypy i runtime wiring budu stabilni.

    Nakon ustava:
    - LLM-based ActionExecutionService put (agent_execute → LLM → Notion) je onemogućen.
    - Job type "agent_execute" se tretira kao legacy i ne izvršava side-effecte.
    """

    def __init__(
        self,
        queue: QueueService,
        *,
        memory: Optional[Any] = None,
        agent_router: Optional[Any] = None,
        write_gateway: Optional[Any] = None,
    ) -> None:
        self.queue = queue

        # Optional wiring (trenutno nije u upotrebi u ovom workeru, ali čuvamo kompatibilnost)
        self.memory = memory
        self.agent_router = agent_router
        self.write_gateway = write_gateway

        # Legacy hook (ranije je ovdje živio ActionExecutionService).
        # Zadržavamo atribut radi eventualne kompatibilnosti, ali je uvijek None.
        self._action_executor: Optional[Any] = None

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
            # Approval gate: ovo nije "crash" biznis logike; jasno logujemo i vraćamo blokadu.
            msg = str(e)
            logger.warning(
                "Job blocked (approval gate) job_id=%s type=%s error=%s",
                job.job_id,
                job.job_type,
                msg,
            )
            await self.queue.nack(job.job_id, msg)
            return {"ok": False, "error": msg}
        except Exception as e:  # noqa: BLE001
            err = repr(e)
            logger.exception(
                "Job failed job_id=%s type=%s error=%s", job.job_id, job.job_type, err
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
        v = payload.get("approval_id")
        if isinstance(v, str) and v.strip():
            return v.strip()

        md = payload.get("metadata")
        if isinstance(md, dict):
            v = md.get("approval_id")
            if isinstance(v, str) and v.strip():
                return v.strip()

        cmd = payload.get("command")
        if isinstance(cmd, dict):
            v = cmd.get("approval_id")
            if isinstance(v, str) and v.strip():
                return v.strip()

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
        """
        approval_id = cls._coalesce_approval_id(payload)
        return {"approval_id": approval_id} if approval_id else {}

    async def _handle_agent_execute(self, job: Job) -> Dict[str, Any]:
        """
        Legacy job_type "agent_execute".

        Historijski:
        - payload.command se slao u ActionExecutionService (LLM-based Notion Ops).

        Nakon ustava:
        - LLM više ne smije biti na write path-u prema Notion-u.
        - Ovaj put NE izvršava nikakve side-effecte.
        - Job se završava sa jasnom porukom da je legacy onemogućen.

        Napomena:
        - I dalje enforce-amo approval gate (ako approval nije validan, baca PermissionError).
        - Rezultat je dict koji će biti ACK-ovan u queue-u (da job ne loop-a).
        """
        payload = job.payload if isinstance(job.payload, dict) else {}
        cmd = payload.get("command")
        if not isinstance(cmd, dict):
            raise ValueError("agent_execute requires payload.command (dict)")

        command_id = str(cmd.get("id") or "agent_execute")
        command_type = str(cmd.get("type") or "agent_execute")

        # Approval gate (read-only check, bez side-effecta)
        approval_ctx = self._extract_approval_context(payload)
        require_approval_or_block(
            command_id=command_id,
            command_type=command_type,
            context=approval_ctx,
        )

        # Legacy execution put je onemogućen:
        return {
            "ok": False,
            "job_type": job.job_type,
            "error": "agent_execute_disabled",
            "message": (
                "Job type 'agent_execute' (LLM-based ActionExecutionService) je legacy i onemogućen. "
                "Koristi canonical approval-based Notion Ops Executor "
                "(/api/execute/raw → approval → NotionService/ExecutionOrchestrator)."
            ),
            "approval_context": approval_ctx,
        }
