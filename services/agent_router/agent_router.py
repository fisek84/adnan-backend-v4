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
import asyncio
import uuid
import json

from openai import OpenAI

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
        # OpenAI klijent – koristi OPENAI_API_KEY iz okoline
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # SINGLE SOURCE OF TRUTH za sve agent info
        self._registry = registry or AgentRegistryService()
        self._load = load_balancer or AgentLoadBalancerService()
        self._health = health_service or AgentHealthService()
        self._isolation = isolation_service or AgentIsolationService()

    # =====================================================
    # AGENT SELECTION (DETERMINISTIC, SCALABLE)
    # =====================================================
    def _select_agent(self, command: str) -> Optional[Dict[str, Any]]:
        """
        Deterministički odabir agenta:
        - radi isključivo na podacima iz registry-ja
        - poštuje isolation, health i load
        - NEMA side efekata
        """
        agents = self._registry.get_agents_with_capability(command)

        for agent in agents:
            name = agent["agent_name"]

            # 1) izolovan agent se preskače
            if self._isolation.is_isolated(name):
                continue

            # 2) ne-zdrav agent se preskače
            if not self._health.is_healthy(name):
                continue

            # 3) agent pod backpressure-om se preskače
            if not self._load.can_accept(name):
                continue

            # deterministički: prvi validan po registry redoslijedu
            return agent

        return None

    # =====================================================
    # ROUTE (NO EXECUTION, NO SIDE EFFECTS)
    # =====================================================
    def route(self, command: Dict[str, str]) -> Dict[str, Optional[str]]:
        """
        Čisti routing:
        - Ulaz: {"command": "..."}
        - Izlaz: {"agent": <agent_name> | None}
        - NEMA IO, NEMA poziva prema OpenAI-u
        """
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
        Controlled execution:

        payload MORA sadržavati:
        - "command": str
        - "payload": Dict[str, Any] (business data)

        Ovdje:
        - radimo rezervaciju kapaciteta (backpressure)
        - izvršavamo agenta preko OpenAI Assistants API-ja
        - parsiramo JSON odgovor (response_format = json_object)
        - bilježimo health/load signale
        - containment u slučaju grešaka (izolacija agenta)
        """
        command = payload.get("command")
        if not command:
            return {"success": False, "reason": "missing_command"}

        agent = self._select_agent(command)
        if not agent:
            return {
                "success": False,
                "reason": "no_available_agent_or_backpressure",
            }

        agent_name = agent["agent_name"]
        assistant_id = agent.get("metadata", {}).get("assistant_id")

        if not assistant_id:
            return {
                "success": False,
                "reason": "agent_missing_assistant_binding",
                "agent": agent_name,
            }

        execution_id = f"exec_{uuid.uuid4().hex}"

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
            # 1) Kreiramo thread
            thread = self.client.beta.threads.create()

            # 2) User poruka – JSON kao string, response_format = json_object
            user_content = json.dumps(
                {
                    "execution_id": execution_id,
                    "command": command,
                    "payload": payload.get("payload", {}),
                }
            )

            self.client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=user_content,
            )

            # 3) Pokrećemo run
            run = self.client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=assistant_id,
                temperature=0,
                response_format={"type": "json_object"},
            )

            # 4) Polling dok ne bude gotovo
            while run.status not in {"completed", "failed", "cancelled"}:
                await asyncio.sleep(0.3)
                run = self.client.beta.threads.runs.retrieve(
                    thread_id=thread.id,
                    run_id=run.id,
                )

            if run.status != "completed":
                raise RuntimeError(f"agent_run_status={run.status}")

            # 5) Uzimamo zadnju poruku i parsiramo JSON
            messages = self.client.beta.threads.messages.list(
                thread_id=thread.id,
                limit=1,
            )

            if not messages.data:
                raise RuntimeError("no_agent_messages")

            message = messages.data[0]
            if not message.content:
                raise RuntimeError("empty_agent_message_content")

            content_block = message.content[0]

            if getattr(content_block, "type", None) != "text":
                raise RuntimeError("invalid_agent_response_type")

            # assistants v2: text value je u content_block.text.value
            try:
                text_value = content_block.text.value
            except AttributeError:
                # fallback ako SDK vrati dict-like strukturu
                text_value = content_block["text"]["value"]  # type: ignore[index]

            try:
                result_json = json.loads(text_value)
            except json.JSONDecodeError:
                raise RuntimeError("invalid_json_response")

            # ---------------------------------------------
            # SUCCESS SIGNALS
            # ---------------------------------------------
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
            # ---------------------------------------------
            # FAILURE CONTAINMENT
            # ---------------------------------------------
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
            # release backpressure slot
            self._load.release(agent_name)
