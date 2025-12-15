"""
AGENT ROUTER — CANONICAL (FAZA 6 FINAL)

Uloga:
- JEDINO mjesto gdje se vrši agent DELEGATION + EXECUTION
- izbor agenta:
    capability  → AgentRegistryService
    load        → AgentLoadBalancerService
    health      → AgentHealthService
- NEMA governance
- NEMA approval
- NEMA policy
- NEMA UX semantike
"""

from typing import Dict, Any, Optional, List
import os
import asyncio
import uuid

from openai import OpenAI

from services.agent_registry_service import AgentRegistryService
from services.agent_load_balancer_service import AgentLoadBalancerService
from services.agent_health_service import AgentHealthService


class AgentRouter:
    def __init__(
        self,
        registry: Optional[AgentRegistryService] = None,
        load_balancer: Optional[AgentLoadBalancerService] = None,
        health_service: Optional[AgentHealthService] = None,
    ):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # SOURCES OF TRUTH
        self._registry = registry or AgentRegistryService()
        self._load = load_balancer or AgentLoadBalancerService()
        self._health = health_service or AgentHealthService()

    # =====================================================
    # AGENT SELECTION (CAPABILITY + HEALTH + LOAD)
    # =====================================================
    def _select_agent(self, command: str) -> Optional[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []

        agents = self._registry.get_agents_with_capability(command)

        for agent in agents:
            name = agent["agent_name"]

            if not self._health.is_healthy(name):
                continue

            if not self._load.can_accept(name):
                continue

            candidates.append(agent)

        if not candidates:
            return None

        # deterministički: prvi po registry redoslijedu
        return candidates[0]

    # =====================================================
    # ROUTE (NO EXECUTION)
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
    # EXECUTE (AGENT ONLY)
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
            return {"success": False, "reason": "no_available_healthy_agent"}

        agent_name = agent["agent_name"]
        assistant_id = agent.get("metadata", {}).get("assistant_id")

        if not assistant_id:
            return {
                "success": False,
                "reason": "agent_missing_assistant_binding",
                "agent": agent_name,
            }

        execution_id = f"exec_{uuid.uuid4().hex}"
        self._load.reserve(agent_name)

        try:
            thread = self.client.beta.threads.create()

            self.client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content={
                    "execution_id": execution_id,
                    "command": command,
                    "payload": payload.get("payload", {}),
                },
            )

            run = self.client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=assistant_id,
                temperature=0,
                response_format={"type": "json_object"},
            )

            while run.status not in {"completed", "failed", "cancelled"}:
                await asyncio.sleep(0.3)
                run = self.client.beta.threads.runs.retrieve(
                    thread_id=thread.id,
                    run_id=run.id,
                )

            if run.status != "completed":
                raise RuntimeError(f"agent_run_status={run.status}")

            messages = self.client.beta.threads.messages.list(
                thread_id=thread.id,
                limit=1,
            )

            content = messages.data[0].content[0]
            if content["type"] != "output_json":
                raise RuntimeError("invalid_agent_response")

            # SUCCESS SIGNALS
            self._load.record_success(agent_name)
            self._health.mark_heartbeat(agent_name)

            return {
                "success": True,
                "execution_id": execution_id,
                "agent": agent_name,
                "agent_id": agent["agent_id"],
                "result": content["json"],
            }

        except Exception as e:
            self._load.record_failure(agent_name)
            self._health.mark_unhealthy(agent_name, reason=str(e))

            return {
                "success": False,
                "execution_id": execution_id,
                "agent": agent_name,
                "reason": "agent_execution_failed",
                "error": str(e),
            }

        finally:
            self._load.release(agent_name)
