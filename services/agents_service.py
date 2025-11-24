import httpx
import asyncio

class AgentsService:
    """
    Evolia AgentsService v4.1
    Upravljanje AI agentima + Notion integracija
    """

    def __init__(self, notion_token: str, exchange_db_id: str, projects_db_id: str):
        self.token = notion_token
        self.exchange_db_id = exchange_db_id
        self.projects_db_id = projects_db_id

        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {notion_token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            timeout=20.0,
        )

        self._actions = {
            "ping": self._ping,
            "info": self._info,
        }

    # ============================================================
    # ACTIONS
    # ============================================================
    def available_actions(self):
        return list(self._actions.keys())

    async def execute(self, action: str, payload: dict):
        if action not in self._actions:
            raise ValueError(f"Unknown agent action: {action}")

        handler = self._actions[action]

        if asyncio.iscoroutinefunction(handler):
            return await handler(payload)
        return handler(payload)

    # ============================================================
    # HANDLERS
    # ============================================================
    async def _ping(self, payload: dict):
        resp = await self._client.get("https://api.notion.com/v1/users/me")
        try:
            return resp.json()
        except:
            return {"raw": resp.text}

    async def _info(self, payload: dict):
        return {
            "exchange_db_id": self.exchange_db_id,
            "projects_db_id": self.projects_db_id,
            "token_present": bool(self.token),
        }

    # ============================================================
    # UTILITIES
    # ============================================================
    async def close(self):
        try:
            await self._client.aclose()
        except:
            pass