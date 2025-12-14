from typing import Dict, Any, List, Optional
import logging
import time

from services.conversation_state_service import ConversationStateService

logger = logging.getLogger(__name__)


class SOPExecutionManager:
    """
    SOPExecutionManager — SEQUENTIAL EXECUTION (FAZA 5.4)

    Pravila:
    - nema paralelizma
    - nema retry-a
    - nema heuristike
    - nema autonomije
    - SOP samo ORKESTRIRA TASKOVE
    """

    EXECUTION_ENABLED = True  # 🔓 OTVORENO U FAZA 5.4

    def __init__(self):
        self.csi = ConversationStateService()
        logger.info(
            "[SOPExecutionManager] INITIALIZED — SEQUENTIAL EXECUTION ENABLED"
        )

    # ============================================================
    # PUBLIC ENTRYPOINT — SOP EXECUTION
    # ============================================================
    async def execute_plan(
        self,
        execution_plan: List[Dict[str, Any]],
        current_sop: Optional[str] = None,
        *,
        request_id: Optional[str] = None,
    ) -> Dict[str, Any]:

        if not self.EXECUTION_ENABLED:
            logger.warning(
                "[SOPExecutionManager] EXECUTION BLOCKED | sop_id=%s request_id=%s",
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

        started_at = time.time()
        results: List[Dict[str, Any]] = []

        # CSI: SOP -> EXECUTING
        self.csi.start_sop_execution(request_id=request_id)

        for task in execution_plan:
            task_id = task.get("task_id")

            logger.info(
                "[SOPExecutionManager] EXECUTING TASK | sop_id=%s task_id=%s",
                current_sop,
                task_id,
            )

            try:
                # TASK lifecycle (delegacija, ne implementacija)
                self.csi.set_task_create(task=task, request_id=request_id)
                self.csi.set_task_draft(request_id=request_id)
                self.csi.confirm_task(request_id=request_id)
                self.csi.start_task(request_id=request_id)

                # ⛔ stvarno izvršenje taska se dešava DRUGDJE
                # ovdje samo čekamo da bude označen kao DONE ili FAILED

                # Za FAZA 5.4 pretpostavka: TASK executor postavlja stanje
                # CSI se samo čita
                state = self.csi.get().get("state")

                if state == "TASK_FAILED":
                    raise RuntimeError(f"Task failed: {task_id}")

                self.csi.complete_task(request_id=request_id)

                results.append({
                    "task_id": task_id,
                    "status": "DONE",
                })

            except Exception as e:
                logger.error(
                    "[SOPExecutionManager] TASK FAILED | sop_id=%s task_id=%s error=%s",
                    current_sop,
                    task_id,
                    str(e),
                )

                self.csi.fail_task(request_id=request_id)
                self.csi.fail_sop(request_id=request_id)

                return {
                    "success": False,
                    "execution_state": "FAILED",
                    "sop_id": current_sop,
                    "request_id": request_id,
                    "started_at": started_at,
                    "finished_at": time.time(),
                    "summary": f"SOP failed on task {task_id}",
                    "results": results,
                }

        # SVI TASKOVI SU USPJEŠNI
        self.csi.complete_sop(request_id=request_id)

        return {
            "success": True,
            "execution_state": "COMPLETED",
            "sop_id": current_sop,
            "request_id": request_id,
            "started_at": started_at,
            "finished_at": time.time(),
            "summary": "SOP completed successfully",
            "results": results,
        }

    # ============================================================
    # INTERNAL — PARALLEL EXECUTION (STILL FORBIDDEN)
    # ============================================================
    async def _execute_parallel(self, *args, **kwargs):
        raise RuntimeError(
            "Parallel SOP execution is forbidden by system policy."
        )
