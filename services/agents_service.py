import httpx
import logging
import asyncio

# Inicijalizacija loggera
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

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
            timeout=60.0,  # Povećaj timeout na 60 sekundi za stabilnost
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
        logger.info(f"Executing action: {action} with payload: {payload}")

        if action not in self._actions:
            logger.error(f"Unknown agent action: {action}")
            raise ValueError(f"Unknown agent action: {action}")

        handler = self._actions[action]

        # Logovanje pre slanja HTTP zahteva
        logger.info(f"Sending request to backend with action: {action}, payload: {payload}")

        # Poslati HTTP zahtev prema backendu
        if asyncio.iscoroutinefunction(handler):
            try:
                response = await self._client.post("http://127.0.0.1:8000/tasks", json=payload)
                logger.info(f"Response from backend: {response.text}")
                response.raise_for_status()  # Ako je status greška, podiže HTTPError
                return await handler(payload)
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTP error occurred while communicating with backend: {e}")
                return {"error": f"HTTP error: {e.response.status_code}"}
            except Exception as e:
                logger.error(f"Error while sending request to backend: {e}")
                return {"error": str(e)}

        return handler(payload)

    # ============================================================
    # HANDLERS
    # ============================================================
    async def _ping(self, payload: dict):
        try:
            logger.info("Pinging Notion API...")
            resp = await self._client.get("https://api.notion.com/v1/users/me")
            resp.raise_for_status()  # Ako je status greška, podiže HTTPError
            resp_data = resp.json()
            logger.info(f"Ping successful, response: {resp_data}")
            return resp_data
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error occurred while pinging Notion: {e}")
            return {"error": f"HTTP error: {e.response.status_code}"}
        except Exception as e:
            logger.error(f"Error while pinging Notion API: {e}")
            return {"error": str(e)}

    async def _info(self, payload: dict):
        logger.info(f"Returning info for exchange_db_id: {self.exchange_db_id} and projects_db_id: {self.projects_db_id}")
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
            logger.info("Closing HTTP client...")
            await self._client.aclose()
        except Exception as e:
            logger.error(f"Error while closing client: {e}")
            pass
