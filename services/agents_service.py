import httpx


class AgentsService:
    """
    Evolia AgentsService v4.1
    - Upravljanje AI agentima
    - Povezan sa Notion bazama (Exchange + Projects)
    - Minimalistic, stabilan, proširiv
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

        # Ako je async handler → await
        if hasattr(handler, "__call__") and asyncio.iscoroutinefunction(handler):
            return await handler(payload)

        # Ako je sync → direktno
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