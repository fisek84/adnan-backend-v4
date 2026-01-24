# services/agent_router/agent_router.py

"""
AGENT ROUTER — CANONICAL (FAZA 13 / SCALING)

Uloga:
- JEDINO mjesto gdje se vrši agent DELEGATION + EXECUTION
- deterministički routing
- eksplicitni backpressure
- failure containment
- NEMA governance
- NEMA approval
- NEMA UX semantike
"""

from typing import Dict, Any, Optional
import os
import uuid
import json

from services.agent_router.executor_factory import get_executor

from services.agent_registry_service import AgentRegistryService
from services.agent_load_balancer_service import AgentLoadBalancerService
from services.agent_health_service import AgentHealthService
from services.agent_isolation_service import AgentIsolationService


class AgentRouter:
    def __init__(
        self,
        registry: Optional[AgentRegistryService] = None,
        load_balancer: Optional[AgentLoadBalancerService] = None,
        health_service: Optional[AgentHealthService] = None,
        isolation_service: Optional[AgentIsolationService] = None,
    ):
        # SOURCES OF TRUTH
        self._registry = registry or AgentRegistryService()
        self._load = load_balancer or AgentLoadBalancerService()
        self._health = health_service or AgentHealthService()
        self._isolation = isolation_service or AgentIsolationService()

    # =====================================================
    # AGENT SELECTION (DETERMINISTIC, SCALABLE)
    # =====================================================
    def _select_agent(self, command: str) -> Optional[Dict[str, Any]]:
        agents = self._registry.get_agents_with_capability(command)

        for agent in agents:
            name = agent["agent_name"]

            if self._isolation.is_isolated(name):
                continue

            if not self._health.is_healthy(name):
                continue

            if not self._load.can_accept(name):
                continue

            # deterministički: prvi validan po registry redoslijedu
            return agent

        return None

    # =====================================================
    # ROUTE (NO EXECUTION, NO SIDE EFFECTS)
    # =====================================================
    def route(self, command: Dict[str, str]) -> Dict[str, Optional[str]]:
        cmd = command.get("command")
        if not cmd:
            return {"agent": None}

        agent = self._select_agent(cmd)
        if not agent:
            return {"agent": None}

        return {"agent": agent["agent_name"]}

    # =====================================================
    # EXECUTE (CONTROLLED, BACKPRESSURE AWARE)
    # =====================================================
    async def execute(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """
        payload MUST contain:
        - command
        - payload (business data)
        """

        command = payload.get("command")
        if not command:
            return {"success": False, "reason": "missing_command"}

        agent = self._select_agent(command)
        if not agent:
            return {"success": False, "reason": "no_available_agent_or_backpressure"}

        agent_name = agent["agent_name"]
        assistant_id = agent.get("metadata", {}).get("assistant_id")
        entrypoint = agent.get("metadata", {}).get("entrypoint")

        if not assistant_id:
            return {
                "success": False,
                "reason": "agent_missing_assistant_binding",
                "agent": agent_name,
            }

        # allow caller to pin execution_id (idempotency/orchestrator)
        execution_id = payload.get("execution_id") or f"exec_{uuid.uuid4().hex}"

        # -------------------------------------------------
        # BACKPRESSURE RESERVATION
        # -------------------------------------------------
        try:
            self._load.reserve(agent_name)
        except Exception:
            return {
                "success": False,
                "reason": "backpressure_rejected",
                "agent": agent_name,
            }

        try:
            # Special handling for CEO Advisor: use Python entrypoint, not OpenAI executor
            if agent_name == "ceo_advisor" and entrypoint:
                # Dynamically import and call the entrypoint function
                import importlib

                module_path, func_name = entrypoint.split(":")
                mod = importlib.import_module(module_path)
                func = getattr(mod, func_name)
                # Prepare AgentInput if needed, else pass payload
                agent_input = payload.get("payload", {})
                # If async, await; else, call directly
                import inspect

                if inspect.iscoroutinefunction(func):
                    result = await func(agent_input, ctx={})
                else:
                    result = func(agent_input, ctx={})
                self._load.record_success(agent_name)
                self._health.mark_heartbeat(agent_name)
                return {
                    "success": True,
                    "execution_id": execution_id,
                    "agent": agent_name,
                    "agent_id": agent.get("agent_id"),
                    "result": result,
                }

            # Default: OpenAI executor for all other agents
            user_content = json.dumps(
                {
                    "execution_id": execution_id,
                    "command": command,
                    "payload": payload.get("payload", {}),
                },
                ensure_ascii=False,
            )

            executor = get_executor(purpose="agent_router")

            instructions = (agent.get("metadata") or {}).get("instructions") or (
                agent.get("metadata") or {}
            ).get("system_prompt")

            if (
                os.getenv("OPENAI_API_MODE") or "assistants"
            ).strip().lower() == "responses":
                if not isinstance(instructions, str) or not instructions.strip():
                    raise RuntimeError(
                        "responses_mode_requires_agent_instructions_in_metadata"
                    )

            result_json = await executor.execute(
                {
                    "assistant_id": assistant_id,
                    "content": user_content,
                    "instructions": instructions,
                    "response_format": {"type": "json_object"},
                    "temperature": 0,
                    "parse_mode": "text_json",
                    "limit": 10,
                    "input": user_content,
                    "allow_tools": False,
                }
            )

            self._load.record_success(agent_name)
            self._health.mark_heartbeat(agent_name)

            return {
                "success": True,
                "execution_id": execution_id,
                "agent": agent_name,
                "agent_id": agent.get("agent_id"),
                "result": result_json,
            }

        except Exception as e:
            self._load.record_failure(agent_name)
            self._health.mark_unhealthy(agent_name, reason=str(e))
            self._isolation.isolate(agent_name)
            return {
                "success": False,
                "execution_id": execution_id,
                "agent": agent_name,
                "reason": "agent_execution_failed",
                "error": str(e),
            }
        finally:
            self._load.release(agent_name)
