"""
AGENT LOAD BALANCER SERVICE — CANONICAL (FAZA 6)

Uloga:
- JEDINO mjesto za load / concurrency kontrolu agenata
- NEMA execution
- NEMA routing odluke
- NEMA governance / approval / policy
- deterministički i side-effect free (osim runtime metrika)

AgentLoadBalancerService ≠ AgentRouter
AgentLoadBalancerService ≠ AgentRegistryService
"""

from typing import Dict, Any
import time


class AgentLoadBalancerService:
    def __init__(self):
        # runtime state po agentu
        self._runtime: Dict[str, Dict[str, Any]] = {}

    # =========================================================
    # INTERNAL — RUNTIME INIT
    # =========================================================
    def _ensure(self, agent_name: str) -> Dict[str, Any]:
        if agent_name not in self._runtime:
            self._runtime[agent_name] = {
                "current_load": 0,
                "max_concurrency": 1,
                "disabled_until": None,
                "failure_count": 0,
                "failure_threshold": 3,
                "cooldown_seconds": 60,
            }
        return self._runtime[agent_name]

    # =========================================================
    # PUBLIC API
    # =========================================================
    def can_accept(self, agent_name: str) -> bool:
        state = self._ensure(agent_name)
        now = time.time()

        if state["disabled_until"] and now < state["disabled_until"]:
            return False

        if state["current_load"] >= state["max_concurrency"]:
            return False

        return True

    def reserve(self, agent_name: str) -> None:
        state = self._ensure(agent_name)
        state["current_load"] += 1

    def release(self, agent_name: str) -> None:
        state = self._ensure(agent_name)
        state["current_load"] = max(state["current_load"] - 1, 0)

    # =========================================================
    # FAILURE ACCOUNTING
    # =========================================================
    def record_failure(self, agent_name: str) -> None:
        state = self._ensure(agent_name)
        state["failure_count"] += 1

        if state["failure_count"] >= state["failure_threshold"]:
            state["disabled_until"] = time.time() + state["cooldown_seconds"]

    def record_success(self, agent_name: str) -> None:
        state = self._ensure(agent_name)
        state["failure_count"] = 0

    # =========================================================
    # SNAPSHOT (READ-ONLY)
    # =========================================================
    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        return {
            agent: {
                "current_load": s["current_load"],
                "max_concurrency": s["max_concurrency"],
                "disabled_until": s["disabled_until"],
                "failure_count": s["failure_count"],
                "read_only": True,
            }
            for agent, s in self._runtime.items()
        }
