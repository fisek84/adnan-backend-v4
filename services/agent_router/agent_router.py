# services/agent_router/agent_router.py

import httpx


class AgentRouter:
    """
    Centralni mozak delegacije.
    Adnan.ai određuje KOJI agent izvršava određenu operaciju.
    """

    def __init__(self):
        # Danas imamo samo 1 agenta: Notion Ops
        # U budućnosti ovdje dodajemo OutreachAgent, CRM, SalesOps itd.
        self.agents = {
            "notion": "http://localhost:8000/ops/execute"
        }

    def route(self, command: dict) -> dict:
        """
        Prima notion_command ili buduću komandu
        i odlučuje KOM AGENTU pripada.
        """

        cmd_name = command.get("command", "")

        # -------------------------
        # 1. NOTION OPS KOMANDE
        # -------------------------
        if cmd_name in [
            "create_database_entry",
            "update_database_entry",
            "query_database",
            "create_page",
            "retrieve_page_content"
        ]:
            return {
                "agent": "notion",
                "endpoint": self.agents["notion"]
            }

        # -------------------------
        # 2. NO MATCH → UNKNOWN
        # -------------------------
        return {
            "agent": "unknown",
            "endpoint": None
        }

    async def execute(self, command: dict) -> dict:
        """
        Šalje komandu nadležnom agentu (delegacija).
        """

        route = self.route(command)

        if not route["endpoint"]:
            return {
                "success": False,
                "reason": "No valid agent found for this command",
                "command": command
            }

        endpoint = route["endpoint"]

        async with httpx.AsyncClient() as client:
            response = await client.post(
                endpoint,
                json={
                    "command": command.get("command"),
                    "payload": command
                }
            )

        try:
            data = response.json()
        except:
            data = {"error": "Agent returned non-JSON response"}

        return {
            "success": True,
            "agent": route["agent"],
            "agent_response": data
        }
