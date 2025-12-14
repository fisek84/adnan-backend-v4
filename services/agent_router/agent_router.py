from typing import Dict, Optional, List
import os
import asyncio
import time
import uuid

from openai import OpenAI


class AgentRouter:
    """
    AgentRouter — KANONSKI AGENT OS ENTRYPOINT

    FAZA 7:
    #14 agent identity & capability model
    #15 agent health monitoring
    #16 dynamic agent assignment
    #17 load balancing
    #18 agent isolation
    #19 agent deactivation / recovery (THIS FILE)

    NAPOMENA:
    - Router bira agenta
    - Router NE izvršava posao
    - Agent lifecycle je ovdje zaključen
    """

    def __init__(self):
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

        # =========================================================
        # AGENT REGISTRY
        # =========================================================
        self.agent_registry: Dict[str, Dict] = {
            "notion_ops": {
                # ---- identity ----
                "agent_id": "agent.notion_ops",
                "type": "executor",
                "status": "active",   # active | degraded | disabled
                "version": "1.0.0",

                # ---- capability model ----
                "capabilities": {
                    "create_database_entry",
                    "update_database_entry",
                    "query_database",
                    "create_page",
                    "retrieve_page_content",
                    "delete_page",
                },

                # ---- execution binding ----
                "assistant_id": os.getenv("NOTION_OPS_ASSISTANT_ID"),
                "response_format": "json_object",
                "temperature": 0,

                # ---- runtime control ----
                "max_concurrency": 1,
                "current_load": 0,
                "last_heartbeat": None,

                # ---- lifecycle control ----
                "failure_count": 0,
                "failure_threshold": 3,
                "cooldown_seconds": 60,
                "disabled_until": None,
            }
        }

    # =========================================================
    # AGENT LOOKUP (WITH RECOVERY)
    # =========================================================
    def get_agent(self, agent_name: str) -> Optional[Dict]:
        agent = self.agent_registry.get(agent_name)
        if not agent:
            return None

        # auto-recovery
        if agent["status"] == "disabled":
            until = agent.get("disabled_until")
            if until and time.time() >= until:
                agent["status"] = "active"
                agent["failure_count"] = 0
                agent["disabled_until"] = None

        if agent.get("status") != "active":
            return None

        return agent

    # =========================================================
    # DYNAMIC SELECTION
    # =========================================================
    def select_agent(self, capability: str) -> Optional[str]:
        candidates: List[tuple[str, Dict]] = []

        for name, agent in self.agent_registry.items():
            if agent["status"] != "active":
                continue
            if capability not in agent.get("capabilities", set()):
                continue
            if agent["current_load"] >= agent["max_concurrency"]:
                continue
            candidates.append((name, agent))

        if not candidates:
            return None

        candidates.sort(key=lambda x: x[1]["current_load"])
        return candidates[0][0]

    # =========================================================
    # ROUTING
    # =========================================================
    def route(self, command: dict) -> Dict[str, Optional[str]]:
        cmd_name = command.get("command")
        if not cmd_name:
            return {"agent": None, "assistant_id": None}

        agent_name = self.select_agent(cmd_name)
        if not agent_name:
            return {"agent": None, "assistant_id": None}

        agent = self.agent_registry[agent_name]
        return {
            "agent": agent_name,
            "assistant_id": agent["assistant_id"],
        }

    # =========================================================
    # EXECUTION (ISOLATED + LIFECYCLE CONTROLLED)
    # =========================================================
    async def execute(self, command: dict) -> dict:
        route = self.route(command)

        if not route.get("assistant_id"):
            return {
                "success": False,
                "reason": "no_available_agent",
                "command": command,
            }

        agent_name = route["agent"]
        agent = self.get_agent(agent_name)

        if not agent:
            return {
                "success": False,
                "reason": "agent_not_available",
                "agent": agent_name,
            }

        execution_id = f"exec_{uuid.uuid4().hex}"
        isolated_command = {
            "execution_id": execution_id,
            "agent_id": agent["agent_id"],
            "payload": command,
        }

        agent["current_load"] += 1

        try:
            thread = self.client.beta.threads.create()

            self.client.beta.threads.messages.create(
                thread_id=thread.id,
                role="user",
                content=isolated_command,
            )

            run = self.client.beta.threads.runs.create(
                thread_id=thread.id,
                assistant_id=agent["assistant_id"],
                temperature=agent["temperature"],
                response_format={"type": agent["response_format"]},
            )

            while True:
                run = self.client.beta.threads.runs.retrieve(
                    thread_id=thread.id,
                    run_id=run.id,
                )

                if run.status in {"completed", "failed", "cancelled"}:
                    break

                await asyncio.sleep(0.3)

            if run.status != "completed":
                raise RuntimeError(f"run_status={run.status}")

            messages = self.client.beta.threads.messages.list(
                thread_id=thread.id,
                limit=1,
            )

            content = messages.data[0].content[0]
            if content["type"] != "output_json":
                raise RuntimeError("invalid_response_format")

            # SUCCESS → reset failure counter
            agent["failure_count"] = 0

            return {
                "success": True,
                "agent": agent_name,
                "agent_id": agent["agent_id"],
                "execution_id": execution_id,
                "agent_response": content["json"],
            }

        except Exception as e:
            # FAILURE ACCOUNTING
            agent["failure_count"] += 1

            if agent["failure_count"] >= agent["failure_threshold"]:
                agent["status"] = "disabled"
                agent["disabled_until"] = time.time() + agent["cooldown_seconds"]

            return {
                "success": False,
                "reason": "agent_execution_failed",
                "agent": agent_name,
                "execution_id": execution_id,
                "error": str(e),
                "status": agent["status"],
            }

        finally:
            agent["current_load"] = max(agent["current_load"] - 1, 0)
