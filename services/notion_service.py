import aiohttp
from typing import Dict, Any, Optional
import logging

_global_notion_service = None


def set_notion_service(instance):
    global _global_notion_service
    _global_notion_service = instance


def get_notion_service():
    if _global_notion_service is None:
        raise RuntimeError("NotionService has not been initialized yet.")
    return _global_notion_service


class NotionService:
    def __init__(
        self,
        api_key: str,
        goals_db_id: str,
        tasks_db_id: str,
        projects_db_id: str,
        active_goals_db_id: str = None,
        agent_exchange_db_id: str = None,
        agent_projects_db_id: str = None,
        ai_weekly_summary_db_id: str = None,
        blocked_goals_db_id: str = None,
        completed_goals_db_id: str = None,
        lead_db_id: str = None,
        kpi_db_id: str = None,
        flp_db_id: str = None
    ):
        self.api_key = api_key
        self.goals_db_id = goals_db_id
        self.tasks_db_id = tasks_db_id
        self.projects_db_id = projects_db_id

        self.active_goals_db_id = active_goals_db_id
        self.agent_exchange_db_id = agent_exchange_db_id
        self.agent_projects_db_id = agent_projects_db_id
        self.ai_weekly_summary_db_id = ai_weekly_summary_db_id
        self.blocked_goals_db_id = blocked_goals_db_id
        self.completed_goals_db_id = completed_goals_db_id
        self.lead_db_id = lead_db_id
        self.kpi_db_id = kpi_db_id
        self.flp_db_id = flp_db_id

        self.session: Optional[aiohttp.ClientSession] = None

        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)

    # ------------------------------------------------------------
    # SESSION HANDLING
    # ------------------------------------------------------------
    async def _get_session(self) -> aiohttp.ClientSession:
        if self.session is None or self.session.closed:
            self.session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    "Notion-Version": "2022-06-28"
                }
            )
        return self.session

    async def _safe_request(self, method: str, url: str, payload: Dict[str, Any] = None):
        session = await self._get_session()
        try:
            async with session.request(method, url, json=payload) as response:
                status = response.status
                text = await response.text()

                if status not in (200, 201, 202):
                    self.logger.error(
                        f"Notion API Error {status} - URL: {url} - Response: {text}"
                    )
                    return {
                        "ok": False,
                        "status": status,
                        "error": text
                    }

                data = await response.json() if text else {}

                return {
                    "ok": True,
                    "status": status,
                    "data": data
                }

        except Exception as e:
            return {"ok": False, "status": 500, "error": str(e)}

    # ------------------------------------------------------------
    # WRAPPERS
    # ------------------------------------------------------------
    async def create_page(self, payload: Dict[str, Any]):
        return await self._safe_request("POST", "https://api.notion.com/v1/pages", payload)

    async def update_page(self, page_id: str, payload: Dict[str, Any]):
        return await self._safe_request("PATCH", f"https://api.notion.com/v1/pages/{page_id}", payload)

    async def query_database(self, db_id: str, filter_payload=None):
        return await self._safe_request(
            "POST",
            f"https://api.notion.com/v1/databases/{db_id}/query",
            filter_payload or {}
        )

    # ------------------------------------------------------------
    # DELETE / ARCHIVE PAGE
    # ------------------------------------------------------------
    async def delete_page(self, page_id: str):
        url = f"https://api.notion.com/v1/pages/{page_id}"
        payload = {"archived": True}

        session = await self._get_session()

        try:
            async with session.patch(url, json=payload) as response:
                status = response.status
                text = await response.text()

                if status not in (200, 202):
                    return {"ok": False, "status": status, "error": text}

                return {"ok": True, "status": status}

        except Exception as e:
            return {"ok": False, "status": 500, "error": str(e)}

    # ------------------------------------------------------------
    # TASKS — CREATE (FIXED)
    # ------------------------------------------------------------
    async def create_task(self, task, notion_goal_id: Optional[str] = None):
        self.logger.info(f"Creating Notion task: {task.title}")

        goal_relation = None
        if notion_goal_id:
            goal_relation = [{"id": notion_goal_id}]

        props = {
            "Name": {"title": [{"text": {"content": task.title}}]},
            "Description": {"rich_text": [{"text": {"content": task.description or ""}}]},
            "Status": {"select": {"name": task.status}},
            "Order": {"number": task.order},
            "Task ID": {"rich_text": [{"text": {"content": task.id}}]},
        }

        if goal_relation:
            props["Goal"] = {"relation": goal_relation}

        if task.deadline:
            props["Deadline"] = {"date": {"start": task.deadline}}

        if task.priority:
            props["Priority"] = {"select": {"name": task.priority}}

        payload = {
            "parent": {"database_id": self.tasks_db_id},
            "properties": props
        }

        response = await self.create_page(payload)

        if response["ok"]:
            self.logger.info(f"Task synced to Notion with ID: {response['data']['id']}")
        else:
            self.logger.error(f"Failed to create task in Notion: {response}")

        return response

    # =====================================================================
    # SMART PROCESS — PLAYBOOK + ORCHESTRATOR INTEGRATION
    # =====================================================================
    async def smart_process(self, user_input: str, target_db: Optional[str]):
        """
        Orchestrator šalje user_input + target_db (od Playbook Engine-a).
        Ovdje se input pretvara u stvarne Notion API operacije.

        target_db može biti: tasks, goals, projects, SOP baze ili bilo koja druga Notion DB.
        """

        if not target_db:
            return {
                "ok": False,
                "error": "Playbook nije mogao odrediti Notion database."
            }

        text = user_input.lower()

        # ============================================================
        # CREATE ENTRY (KREIRAJ / DODAJ / NAPRAVI)
        # ============================================================
        if any(w in text for w in ["dodaj", "napravi", "kreiraj", "create", "add"]):
            title = user_input.strip()
            payload = {
                "parent": {"database_id": target_db},
                "properties": {
                    "Name": {"title": [{"text": {"content": title}}]}
                }
            }
            return await self.create_page(payload)

        # ============================================================
        # QUERY / LIST / PREGLED
        # ============================================================
        if any(w in text for w in ["prikaži", "pokaži", "lista", "list", "query", "svi", "pregled"]):
            return await self.query_database(target_db)

        # ============================================================
        # DEFAULT — fallback signal Orchestratoru
        # ============================================================
        return {
            "ok": True,
            "note": "Smart Process primljen, ali nije prepoznata specifična operacija.",
            "db": target_db
        }

    # =====================================================================
    # SOP HANDLER (NEW)
    # =====================================================================
    async def handle_sop(self, user_input: str):
        """
        SOP requests se delegiraju prema SOP bazama definisanim u PlaybookEngine mappingu.
        """
        from services.decision_engine.playbook_engine import get_db_id

        sop_db = get_db_id("sop")
        if not sop_db:
            return {"ok": False, "error": "Nema SOP baze u mappingu."}

        return await self.smart_process(user_input, sop_db)

    # =====================================================================
    # GENERAL Notion PROCESS (NEW)
    # =====================================================================
    async def process(self, user_input: str):
        """
        Generalni handler koji pronalazi odgovarajuću Notion bazu putem fuzzy matching-a.
        """
        from services.decision_engine.playbook_engine import get_db_id

        db = get_db_id(user_input)
        if not db:
            return {"ok": False, "error": "Ne mogu pronaći odgovarajuću Notion bazu."}

        return await self.smart_process(user_input, db)
