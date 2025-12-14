from typing import Dict, Any, List, Optional
import logging

logger = logging.getLogger(__name__)


class SOPExecutionManager:
    """
    SOPExecutionManager — EXECUTION GATED (KANONSKI)

    STATUS:
    - SOP execution je NAMJERNO ISKLJUČEN
    - NEMA izvršenja
    - NEMA delegacije
    - NEMA heuristike
    - NEMA side-effecta

    Ovaj modul postoji radi:
    - strukture
    - buduće reaktivacije kada execution bude dozvoljen
    """

    EXECUTION_ENABLED = False  # 🔒 APSOLUTNI HARD GATE

    def __init__(self):
        logger.warning(
            "[SOPExecutionManager] INITIALIZED — EXECUTION DISABLED (KANON)"
        )

    # ============================================================
    # PUBLIC ENTRYPOINT — SOP EXECUTION (BLOCKED)
    # ============================================================
    async def execute_plan(
        self,
        execution_plan: List[Dict[str, Any]],
        current_sop: Optional[str] = None,
        *,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:

        logger.warning(
            "[SOPExecutionManager] BLOCKED execution attempt | sop_id=%s request_id=%s",
            current_sop,
            request_id,
        )

        return {
            "success": False,
            "execution_state": "BLOCKED",
            "sop_id": current_sop,
            "request_id": request_id,
            "started_at": None,
            "finished_at": None,
            "summary": "SOP execution is disabled by system policy.",
            "results": [],
        }

    # ============================================================
    # INTERNAL — EXECUTION DISABLED
    # ============================================================
    async def _execute_parallel(self, *args, **kwargs):
        raise RuntimeError(
            "SOPExecutionManager is disabled. Parallel execution is not allowed."
        )

    async def _execute_step(self, *args, **kwargs):
        raise RuntimeError(
            "SOPExecutionManager is disabled. Step execution is not allowed."
        )
