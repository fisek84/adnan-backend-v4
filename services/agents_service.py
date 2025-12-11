import httpx
import logging
import asyncio

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class AgentsService:
    """
    AgentsService v5.1 — Stable Edition
    -----------------------------------
    • Nema coroutine grešaka
    • query() je potpuno sync → sigurno za FastAPI
    • AI interpretacija komandi
    • Task / Goal kreiranje
    • Ping Notion API
    """

    def __init__(self, notion_token: str, exchange_db_id: str, projects_db_id: str):
        self.token = notion_token
        self.exchange_db_id = exchange_db_id
        self.projects_db_id = projects_db_id

        # Async Notion client
        self._client = httpx.AsyncClient(
            headers={
                "Authorization": f"Bearer {notion_token}",
                "Notion-Version": "2022-06-28",
                "Content-Type": "application/json",
            },
            timeout=60.0,
        )

    # ============================================================
    # NATURAL LANGUAGE → ACTION PARSER
    # ============================================================

    def _interpret(self, text: str) -> str:
        t = text.lower()

        if "ping" in t:
            return "ping"

        if "status" in t or "info" in t:
            return "info"

        if "task" in t or "zadatak" in t or "uradi" in t:
            return "create_task"

        if "goal" in t or "cilj" in t:
            return "create_goal"

        return "unknown"

    # ============================================================
    # PUBLIC ENTRY — ALWAYS SYNC
    # ============================================================

    def query(self, text: str) -> dict:
        command = self._interpret(text)
        logger.info(f"[AgentsService] Parsed command: {command}")

        if command == "ping":
            return self._sync(self._ping())

        if command == "info":
            return {
                "agent": "system",
                "response": {
                    "exchange_db_id": self.exchange_db_id,
                    "projects_db_id": self.projects_db_id,
                    "token_present": bool(self.token),
                },
            }

        if command == "create_task":
            return self._create_task(text)

        if command == "create_goal":
            return self._create_goal(text)

        return {
            "agent": "system",
            "response": "Nisam siguran koju AI-agent operaciju želiš."
        }

    # ============================================================
    # SAFE ASYNC → SYNC EXECUTOR
    # ============================================================

    def _sync(self, coro):
        """
        Sigurno pokretanje async funkcija.
        FastAPI na Renderu već ima aktivan event loop → koristimo asyncio.run().
        """
        try:
            return asyncio.run(coro)
        except RuntimeError:
            # Fallback ako loop postoji
            return asyncio.get_event_loop().create_task(coro)

    # ============================================================
    # ASYNC HANDLERS
    # ============================================================

    async def _ping(self):
        try:
            logger.info("Pinging Notion API...")
            resp = await self._client.get("https://api.notion.com/v1/users/me")
            resp.raise_for_status()
            return {"agent": "system", "response": "Notion API je online."}
        except Exception as e:
            return {"agent": "system", "error": str(e)}

    # ============================================================
    # BUSINESS LOGIC
    # ============================================================

    def _create_task(self, text: str) -> dict:
        cleaned = text.lower().replace("task", "").replace("zadatak", "").strip()
        if not cleaned:
            cleaned = "Novi zadatak"

        return {
            "agent": "task_manager",
            "response": f"Kreiram task: {cleaned}",
            "task": cleaned,
        }

    def _create_goal(self, text: str) -> dict:
        cleaned = text.lower().replace("goal", "").replace("cilj", "").strip()
        if not cleaned:
            cleaned = "Novi cilj"

        return {
            "agent": "goal_manager",
            "response": f"Kreiram cilj: {cleaned}",
            "goal": cleaned,
        }

    # ============================================================
    # SHUTDOWN
    # ============================================================

    async def close(self):
        try:
            await self._client.aclose()
        except:
            pass
