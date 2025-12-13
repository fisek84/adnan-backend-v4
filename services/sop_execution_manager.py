from typing import Dict, Any, List, Optional
import asyncio
import logging
from datetime import datetime

from services.agents_service import AgentsService

logger = logging.getLogger(__name__)


class SOPExecutionManager:
    """
    SOPExecutionManager — EXECUTION GATED (FAZA E2)

    RULES:
    - No decisions
    - No governance
    - Pass-through execution context only
    """

    EXECUTION_ENABLED = False  # 🔒 HARD GATE

    CONFIDENCE_HIGH = 0.95
    CONFIDENCE_MEDIUM = 0.75

    TIER_MULTIPLIER = {
        "high": 1.0,
        "medium": 0.85,
        "low": 0.65,
    }

    def __init__(self):
        self.agents = AgentsService()

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
            logger.warning("SOP execution blocked (EXECUTION_ENABLED = False)")
            return {
                "success": False,
                "execution_state": "BLOCKED",
                "sop_id": current_sop,
                "request_id": request_id,
                "started_at": None,
                "finished_at": None,
                "summary": "SOP execution is currently disabled.",
                "results": [],
            }

        sop_started_at = datetime.utcnow().isoformat()

        execution_plan = self._optimize_execution_plan(
            execution_plan,
            current_sop=current_sop,
        )

        results: List[Dict[str, Any]] = []

        i = 0
        while i < len(execution_plan):
            step = execution_plan[i]

            # --------------------------------------------
            # PARALLEL BLOCK
            # --------------------------------------------
            if step.get("parallel") is True:
                parallel_steps = [step]
                i += 1

                while i < len(execution_plan) and execution_plan[i].get("parallel") is True:
                    parallel_steps.append(execution_plan[i])
                    i += 1

                parallel_results = await self._execute_parallel(
                    parallel_steps,
                    current_sop=current_sop,
                )
                results.extend(parallel_results)

                if any(
                    r["status"] == "failed" and r.get("critical")
                    for r in parallel_results
                ):
                    break

                continue

            # --------------------------------------------
            # SEQUENTIAL STEP
            # --------------------------------------------
            step_result = await self._execute_step(
                step,
                current_sop=current_sop,
            )
            results.append(step_result)

            if step_result["status"] == "failed" and step_result.get("critical"):
                break

            i += 1

        return self._finalize_sop(
            results,
            current_sop,
            sop_started_at,
            request_id,
        )

    # ============================================================
    # FINALIZE SOP
    # ============================================================
    def _finalize_sop(
        self,
        results: List[Dict[str, Any]],
        sop_id: Optional[str],
        started_at: str,
        request_id: Optional[str],
    ) -> Dict[str, Any]:

        done = [r for r in results if r["status"] == "done"]
        failed = [r for r in results if r["status"] == "failed"]

        success = len(failed) == 0
        execution_state = "COMPLETED" if success else "FAILED"

        return {
            "success": success,
            "execution_state": execution_state,
            "sop_id": sop_id,
            "request_id": request_id,
            "started_at": started_at,
            "finished_at": datetime.utcnow().isoformat(),
            "summary": (
                "SOP uspješno izvršen."
                if success
                else "SOP djelimično ili neuspješno izvršen."
            ),
            "completed_steps": len(done),
            "failed_steps": failed,
            "results": results,
        }

    # ============================================================
    # OPTIMIZATION (UNCHANGED)
    # ============================================================
    def _optimize_execution_plan(
        self,
        execution_plan: List[Dict[str, Any]],
        current_sop: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        try:
            from services.memory_service import MemoryService

            mem = MemoryService()
            optimized: List[Dict[str, Any]] = []

            for step in execution_plan:
                step_id = step.get("step")
                agent = step.get("agent")

                stats = mem.get_execution_stats(
                    decision_type="sop",
                    key=f"{agent}:{step_id}",
                )

                success_rate = stats.get("success_rate", 0.5) if stats else 0.5

                tier = (
                    "high"
                    if success_rate >= self.CONFIDENCE_HIGH
                    else "medium"
                    if success_rate >= self.CONFIDENCE_MEDIUM
                    else "low"
                )

                step["delegation_score"] = round(
                    success_rate * self.TIER_MULTIPLIER[tier], 2
                )

                optimized.append(step)

            return optimized

        except Exception:
            return execution_plan

    # ============================================================
    # PARALLEL EXECUTION
    # ============================================================
    async def _execute_parallel(
        self,
        steps: List[Dict[str, Any]],
        *,
        current_sop: Optional[str],
    ) -> List[Dict[str, Any]]:
        tasks = [
            self._execute_step(step, current_sop=current_sop)
            for step in steps
        ]
        return await asyncio.gather(*tasks)

    # ============================================================
    # STEP EXECUTION (HARDENED)
    # ============================================================
    async def _execute_step(
        self,
        step: Dict[str, Any],
        *,
        current_sop: Optional[str],
    ) -> Dict[str, Any]:

        step_id = step.get("step")
        command = step.get("command")
        payload = step.get("payload", {})
        critical = step.get("critical", False)

        execution_context = {
            "allowed": True,
            "source": "sop_execution_manager",
            "csi_state": "EXECUTING",
            "sop_id": current_sop,
            "step": step_id,
        }

        result = await self.agents.execute(
            command=command,
            payload=payload,
            execution_context=execution_context,
        )

        success = bool(result.get("success"))

        if not success:
            return {
                "step": step_id,
                "status": "failed",
                "critical": critical,
                "confirmed": False,
                "error": result,
            }

        return {
            "step": step_id,
            "status": "done",
            "critical": critical,
            "confirmed": True,
            "result": result,
        }
