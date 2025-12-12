import httpx
from typing import Dict, Optional, Set


class AgentRouter:
    """
    Centralni mozak delegacije (FAZA 11–12).

    - capability-based routing
    - deterministički agent registry
    - spremno za multi-agent sistem
    """

    def __init__(self):
        # -------------------------------------------------
        # AGENT REGISTRY
        # -------------------------------------------------
        self.agent_registry: Dict[str, Dict] = {
            "notion_ops": {
                "type": "notion",
                "capabilities": {
                    "create_database_entry",
                    "update_database_entry",
                    "query_database",
                    "create_page",
                    "retrieve_page_content",
                    "delete_page",
                },
                "endpoint": "http://localhost:8000/ops/execute",
            }
        }

    # -------------------------------------------------
    # ROUTING (BY CAPABILITY)
    # -------------------------------------------------
    def route(self, command: dict) -> Dict[str, Optional[str]]:
        cmd_name = command.get("command")
        if not cmd_name:
            return {"agent": None, "endpoint": None}

        for agent_name, agent in self.agent_registry.items():
            if cmd_name in agent["capabilities"]:
                return {
                    "agent": agent_name,
                    "endpoint": agent["endpoint"],
                }

        return {"agent": None, "endpoint": None}

    # -------------------------------------------------
    # EXECUTION
    # -------------------------------------------------
    async def execute(self, command: dict) -> dict:
        route = self.route(command)

        if not route["endpoint"]:
            return {
                "success": False,
                "reason": "no_matching_agent",
                "command": command,
            }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                route["endpoint"],
                json={
                    "command": command.get("command"),
                    "payload": command,
                },
                timeout=30,
            )

        try:
            agent_response = response.json()
        except Exception:
            agent_response = {
                "error": "invalid_agent_response",
                "raw_response": response.text,
            }

        return {
            "success": True,
            "agent": route["agent"],
            "agent_response": agent_response,
        }
