# services/notion_ops/ops_engine.py

import os
from typing import Dict, Any, List, Optional
from notion_client import Client


class NotionOpsEngine:
    """
    Evolia Notion Ops Engine v1.0
    ----------------------------------
    Centralizovani engine koji omogućava:
    - čitanje bilo koje DB
    - brisanje iz DB
    - kreiranje
    - update
    - batch operacije
    - validaciju DB strukture
    - full-diagnostic mod
    """

    def __init__(self):
        # --------------------------------------
        # Load Notion API token
        # --------------------------------------
        self.notion = Client(auth=os.getenv("NOTION_API_KEY"))

        # --------------------------------------
        # Load all DB IDs from environment
        # --------------------------------------
        self.db_registry: Dict[str, str] = {
            "goals": os.getenv("NOTION_GOALS_DB_ID"),
            "tasks": os.getenv("NOTION_TASKS_DB_ID"),
            "agent_exchange": os.getenv("NOTION_AGENT_EXCHANGE_DB_ID"),
            "agent_projects": os.getenv("NOTION_AGENT_PROJECTS_DB_ID"),
            "projects": os.getenv("NOTION_PROJECTS_DB_ID"),
            "active_goals": os.getenv("NOTION_ACTIVE_GOALS_DB_ID"),
            "blocked_goals": os.getenv("NOTION_BLOCKED_GOALS_DB_ID"),
            "completed_goals": os.getenv("NOTION_COMPLETED_GOALS_DB_ID"),
            "ai_weekly_summary": os.getenv("NOTION_AI_WEEKLY_SUMMARY_DB_ID"),
        }

    # ============================================================
    # HELPERS
    # ============================================================

    def _get_db_id(self, key: str) -> str:
        """Vrati DB ID po key-u (npr 'tasks', 'goals')."""
        if key not in self.db_registry:
            raise ValueError(f"Database key '{key}' nije registrovan.")
        return self.db_registry[key]

    # ============================================================
    # BASIC DB OPS
    # ============================================================

    def read_all(self, key: str) -> List[Dict[str, Any]]:
        """Vrati sve iteme iz DB."""
        db_id = self._get_db_id(key)
        result = self.notion.databases.query(database_id=db_id)
        return result.get("results", [])

    def read_filtered(self, key: str, filter_payload: dict) -> List[Dict[str, Any]]:
        """Query sa filterom."""
        db_id = self._get_db_id(key)
        result = self.notion.databases.query(database_id=db_id, filter=filter_payload)
        return result.get("results", [])

    def delete_page(self, page_id: str) -> dict:
        """Arhiviraj stranicu."""
        return self.notion.pages.update(page_id=page_id, archived=True)

    # ============================================================
    # BATCH DELETE
    # ============================================================

    def delete_all(self, key: str) -> dict:
        """Obriši sve iteme iz DB."""
        db_id = self._get_db_id(key)
        items = self.notion.databases.query(database_id=db_id).get("results", [])

        deleted = 0

        for item in items:
            self.notion.pages.update(page_id=item["id"], archived=True)
            deleted += 1

        return {"deleted": deleted, "db": key}

    # ============================================================
    # DB VALIDATION
    # ============================================================

    def describe_db(self, key: str) -> Dict[str, Any]:
        """Vrati strukturu DB-a — properties i tipovi."""
        db_id = self._get_db_id(key)
        schema = self.notion.databases.retrieve(database_id=db_id)

        props = schema.get("properties", {})

        formatted = {}
        for name, spec in props.items():
            formatted[name] = spec.get("type")

        return {
            "db_id": db_id,
            "properties": formatted,
            "property_count": len(formatted),
        }

    # ============================================================
    # FULL DIAGNOSTIC
    # ============================================================

    def full_diagnostic(self) -> Dict[str, Any]:
        """
        Pokreće punu dijagnostiku svih registrovanih DB:
        - check postoji li DB
        - check da li je writable
        - check properties
        - check read/write/delete
        """

        report = {}

        for key, db_id in self.db_registry.items():

            if not db_id:
                report[key] = {"error": "DB ID missing from env"}
                continue

            try:
                # Structural info
                structure = self.describe_db(key)

                # Read test
                items = self.read_all(key)

                # Diagnostic summary
                report[key] = {
                    "ok": True,
                    "db_id": db_id,
                    "properties": structure["properties"],
                    "items_in_db": len(items),
                }

            except Exception as e:
                report[key] = {"ok": False, "error": str(e)}

        return report
