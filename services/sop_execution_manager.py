from typing import Dict, Any, List, Optional
import asyncio
import logging

from services.agents_service import AgentsService

logger = logging.getLogger(__name__)


class SOPExecutionManager:
    """
    SOPExecutionManager

    FAZA 4:
    - paralelni koraci
    - critical flag
    - status tracking

    FAZA 6:
    - SOP auto-optimizacija (reorder / skip)
    - execution-level learning (step + agent)

    FAZA 7.1:
    - confidence tiers (low / medium / high)
    - soft-skip
    - criticality hardening

    FAZA 8:
    - delegation scoring (8.1)
    - agent preference resolution (8.2)
    - delegation metadata propagation (8.4)

    FAZA 9:
    - cross-SOP bias signal (READ-ONLY)
    """

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
    # PUBLIC ENTRYPOINT
    # ============================================================
    async def execute_plan(
        self,
        execution_plan: List[Dict[str, Any]],
        current_sop: Optional[str] = None,
    ) -> Dict[str, Any]:
        execution_plan = self._optimize_execution_plan(
            execution_plan,
            current_sop=current_sop,
        )

        results: List[Dict[str, Any]] = []

        i = 0
        while i < len(execution_plan):
            step = execution_plan[i]

            # --------------------------------------------
            # PARALELNI BLOK
            # --------------------------------------------
            if step.get("parallel") is True:
                parallel_steps = [step]
                i += 1

                while i < len(execution_plan) and execution_plan[i].get("parallel") is True:
                    parallel_steps.append(execution_plan[i])
                    i += 1

                parallel_results = await self._execute_parallel(parallel_steps)
                results.extend(parallel_results)

                if any(
                    r["status"] == "failed" and r.get("critical")
                    for r in parallel_results
                ):
                    return self._aggregate_results(results)

                continue

            # --------------------------------------------
            # SEKVENCIJALNI KORAK
            # --------------------------------------------
            step_result = await self._execute_step(step)
            results.append(step_result)

            if step_result["status"] == "failed" and step_result.get("critical"):
                break

            i += 1

        return self._aggregate_results(results)

    # ============================================================
    # FAZA 8 + FAZA 9 — OPTIMIZATION + CROSS-SOP BIAS
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

            cross_sop_bias: List[Dict[str, Any]] = []
            if current_sop:
                try:
                    cross_sop_bias = mem.get_cross_sop_bias(current_sop)
                except Exception:
                    cross_sop_bias = []

            for step in execution_plan:
                step_id = step.get("step")
                agent = step.get("agent")

                stats = mem.get_execution_stats(
                    decision_type="sop",
                    key=f"{agent}:{step_id}",
                )

                success_rate = stats.get("success_rate", 0.5) if stats else 0.5

                if success_rate >= self.CONFIDENCE_HIGH:
                    tier = "high"
                elif success_rate >= self.CONFIDENCE_MEDIUM:
                    tier = "medium"
                else:
                    tier = "low"

                delegation_score = round(
                    success_rate * self.TIER_MULTIPLIER[tier], 2
                )

                bias_boost = 0.0
                for b in cross_sop_bias:
                    if b.get("to") == step_id:
                        bias_boost = b.get("success_rate", 0.0) * 0.1
                        break

                effective_confidence = success_rate + bias_boost

                step["_confidence"] = effective_confidence
                step["delegation_score"] = delegation_score
                step["preferred_agent"] = agent
                step["cross_sop_bias"] = round(bias_boost, 2)

                if tier == "high":
                    continue

                if tier == "medium" and step.get("critical"):
                    step["critical"] = False

                optimized.append(step)

            optimized.sort(
                key=lambda s: (
                    s.get("parallel", False),
                    -s.get("_confidence", 0.5),
                )
            )

            for s in optimized:
                s.pop("_confidence", None)

            return optimized

        except Exception:
            return execution_plan

    # ============================================================
    # PARALLEL EXECUTION
    # ============================================================
    async def _execute_parallel(
        self, steps: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        tasks = [self._execute_step(step) for step in steps]
        return await asyncio.gather(*tasks)

    # ============================================================
    # STEP EXECUTION
    # ============================================================
    async def _execute_step(self, step: Dict[str, Any]) -> Dict[str, Any]:
        step_id = step.get("step")
        agent = step.get("preferred_agent") or step.get("agent")
        command = step.get("command")
        payload = step.get("payload", {})
        critical = step.get("critical", False)

        result = await self.agents.execute(
            command=command,
            payload=payload,
        )

        delegation_meta = {
            "agent": agent,
            "preferred_agent": step.get("preferred_agent"),
            "delegation_score": step.get("delegation_score"),
            "cross_sop_bias": step.get("cross_sop_bias"),
        }

        success = bool(result.get("success"))

        try:
            from services.memory_service import MemoryService
            mem = MemoryService()
            mem.record_execution(
                decision_type="sop",
                key=f"{agent}:{step_id}",
                success=success,
            )
        except Exception:
            pass

        if not success:
            return {
                "step": step_id,
                "status": "failed",
                "critical": critical,
                "confirmed": False,
                "error": result,
                "delegation_meta": delegation_meta,
            }

        return {
            "step": step_id,
            "status": "done",
            "critical": critical,
            "confirmed": True,
            "result": result,
            "delegation_meta": delegation_meta,
        }

    # ============================================================
    # AGGREGATION
    # ============================================================
    def _aggregate_results(self, results: List[Dict[str, Any]]) -> Dict[str, Any]:
        done = [r for r in results if r["status"] == "done"]
        failed = [r for r in results if r["status"] == "failed"]

        success = len(failed) == 0
        confirmed = success

        try:
            from services.memory_service import MemoryService

            mem = MemoryService()
            mem.store_decision_outcome(
                decision_type="sop",
                context_type="sop",
                target=None,
                success=success,
                metadata={
                    "completed_steps": len(done),
                    "failed_steps": len(failed),
                },
            )
        except Exception:
            pass

        return {
            "success": success,
            "confirmed": confirmed,
            "summary": (
                "SOP uspješno izvršen."
                if success
                else "SOP djelimično ili neuspješno izvršen."
            ),
            "completed_steps": len(done),
            "failed_steps": failed,
            "results": results,
        }
