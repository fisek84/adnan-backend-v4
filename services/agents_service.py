import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional

from services.notion_ops.ops_engine import NotionOpsEngine

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class AgentsService:
    """
    AgentsService — FAZA E1 (EXECUTION HARDENING)

    Pravila:
    - Agent NE SMIJE izvršavati bez eksplicitnog execution_context
    - NEMA odluka
    - NEMA governance
    - NEMA CSI mutacija
    """

    OVERLOAD_MIN_TOTAL = 5
    OVERLOAD_SUCCESS_THRESHOLD = 0.6

    def __init__(self):
        self.notion_ops = NotionOpsEngine()
        self.agent_name = "notion_ops"

    # ============================================================
    # PUBLIC ASYNC ENTRYPOINT (HARDENED)
    # ============================================================
    async def execute(
        self,
        *,
        command: str,
        payload: Dict[str, Any],
        execution_context: Dict[str, Any],
    ) -> Dict[str, Any]:

        # --------------------------------------------------------
        # HARD EXECUTION GATE (FAZA E1)
        # --------------------------------------------------------
        if not execution_context or execution_context.get("allowed") is not True:
            logger.error(
                "[AgentsService] BLOCKED execution | context=%s",
                execution_context,
            )
            return {
                "success": False,
                "summary": "Agent execution blocked by missing or invalid execution context.",
                "job": None,
            }

        job_id = str(uuid.uuid4())
        started_at = datetime.utcnow().isoformat()

        logger.info(
            "[AgentsService] job_id=%s command=%s source=%s csi=%s",
            job_id,
            command,
            execution_context.get("source"),
            execution_context.get("csi_state"),
        )

        job = {
            "job_id": job_id,
            "status": "queued",
            "command": command,
            "payload": payload,
            "started_at": started_at,
            "finished_at": None,
            "result": None,
            "error": None,
            "agent_state": None,
            "execution_context": execution_context,
        }

        try:
            job["status"] = "running"

            if command in {
                "query_database",
                "create_database_entry",
                "update_database_entry",
                "create_page",
                "retrieve_page_content",
                "delete_page",
            }:
                result = await self.notion_ops.execute(command, payload)
            else:
                raise ValueError("Nepoznata ili nepodržana agent operacija.")

            job["status"] = "done"
            job["result"] = result
            job["finished_at"] = datetime.utcnow().isoformat()

            self._record_agent_execution(success=True)
            job["agent_state"] = self._evaluate_agent_state()

            return {
                "success": True,
                "summary": result.get("summary", "Operacija završena."),
                "job": job,
            }

        except Exception as e:
            logger.exception("[AgentsService] job failed")

            job["status"] = "failed"
            job["error"] = str(e)
            job["finished_at"] = datetime.utcnow().isoformat()

            self._record_agent_execution(success=False)
            job["agent_state"] = self._evaluate_agent_state()

            return {
                "success": False,
                "summary": "Greška tokom izvršenja operacije.",
                "job": job,
            }

    # ============================================================
    # FAZA 7.3 — PASSIVE AGENT STATS
    # ============================================================
    def _record_agent_execution(self, success: bool):
        try:
            from services.memory_service import MemoryService

            mem = MemoryService()
            mem.record_execution(
                decision_type="agent",
                key=self.agent_name,
                success=success,
            )
        except Exception:
            pass

    # ============================================================
    # FAZA 8.3 — SOFT OVERLOAD EVALUATION
    # ============================================================
    def _evaluate_agent_state(self) -> str:
        try:
            from services.memory_service import MemoryService

            mem = MemoryService()
            stats = mem.get_execution_stats(
                decision_type="agent",
                key=self.agent_name,
            )

            if not stats:
                return "normal"

            total = stats.get("total", 0)
            success_rate = stats.get("success_rate", 1.0)

            if (
                total >= self.OVERLOAD_MIN_TOTAL
                and success_rate < self.OVERLOAD_SUCCESS_THRESHOLD
            ):
                return "degraded"

            return "normal"

        except Exception:
            return "unknown"
