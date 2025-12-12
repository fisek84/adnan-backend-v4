import logging
import uuid
from datetime import datetime
from typing import Dict, Any

from services.notion_ops.ops_engine import NotionOpsEngine

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class AgentsService:
    """
    AgentsService — FAZA 3 / KORAK 2

    FAZA 7.3:
    - pasivna agent load awareness (execution stats)

    FAZA 8.3:
    - soft overload protection (READ-ONLY SIGNAL)

    Pravila:
    - NEMA sync/async miješanja
    - NEMA asyncio.run
    - NEMA schedulera
    - JSON serializable output
    """

    OVERLOAD_MIN_TOTAL = 5
    OVERLOAD_SUCCESS_THRESHOLD = 0.6

    def __init__(self):
        self.notion_ops = NotionOpsEngine()
        self.agent_name = "notion_ops"

    # ============================================================
    # PUBLIC ASYNC ENTRYPOINT
    # ============================================================
    async def execute(self, command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        job_id = str(uuid.uuid4())
        started_at = datetime.utcnow().isoformat()

        logger.info(
            "[AgentsService] job_id=%s command=%s",
            job_id,
            command,
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
            "agent_state": None,  # FAZA 8.3
        }

        try:
            # ----------------------------------------------------
            # RUNNING
            # ----------------------------------------------------
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

            # ----------------------------------------------------
            # DONE
            # ----------------------------------------------------
            job["status"] = "done"
            job["result"] = result
            job["finished_at"] = datetime.utcnow().isoformat()

            # FAZA 7.3 — RECORD AGENT SUCCESS
            self._record_agent_execution(success=True)

            # FAZA 8.3 — EVALUATE AGENT STATE (SOFT)
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

            # FAZA 7.3 — RECORD AGENT FAILURE
            self._record_agent_execution(success=False)

            # FAZA 8.3 — EVALUATE AGENT STATE (SOFT)
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
        """
        Pasivno bilježenje execution signala.
        Nikad ne smije srušiti agenta.
        """
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
        """
        READ-ONLY evaluacija stanja agenta.
        NEMA side-effecta.
        """
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
