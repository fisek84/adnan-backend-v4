# services/notion_ops/ops_engine.py

import os
from datetime import datetime
from typing import Dict, Any, List
from notion_client import Client


class NotionOpsEngine:
    """
    NotionOpsEngine — Canonical Agent Worker

    FAZA 3 / KORAK 3:
    - Svaka operacija se auditira u Notion (agent_exchange)
    """

    def __init__(self):
        self.notion = Client(auth=os.getenv("NOTION_API_KEY"))

        self.db_registry: Dict[str, str] = {
            "goals": os.getenv("NOTION_GOALS_DB_ID"),
            "tasks": os.getenv("NOTION_TASKS_DB_ID"),
            "projects": os.getenv("NOTION_PROJECTS_DB_ID"),
            "agent_exchange": os.getenv("NOTION_AGENT_EXCHANGE_DB_ID"),
            "agent_projects": os.getenv("NOTION_AGENT_PROJECTS_DB_ID"),
            "active_goals": os.getenv("NOTION_ACTIVE_GOALS_DB_ID"),
            "blocked_goals": os.getenv("NOTION_BLOCKED_GOALS_DB_ID"),
            "completed_goals": os.getenv("NOTION_COMPLETED_GOALS_DB_ID"),
            "ai_weekly_summary": os.getenv("NOTION_AI_WEEKLY_SUMMARY_DB_ID"),
        }

    # ============================================================
    # PUBLIC AGENT ENTRYPOINT
    # ============================================================
    async def execute(self, command: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            if command == "query_database":
                result = self._query_database(payload)

            elif command == "create_database_entry":
                result = self._create_database_entry(payload)

            elif command == "update_database_entry":
                result = self._update_database_entry(payload)

            elif command == "create_page":
                result = self._create_page(payload)

            elif command == "retrieve_page_content":
                result = self._retrieve_page_content(payload)

            elif command == "delete_page":
                result = self._delete_page(payload)

            else:
                result = {
                    "success": False,
                    "summary": "Nepoznata Notion operacija.",
                    "command": command,
                }

            # ----------------------------------------------------
            # AUDIT (BEST EFFORT)
            # ----------------------------------------------------
            self._audit_operation(
                command=command,
                payload=payload,
                result=result,
            )

            return result

        except Exception as e:
            error_result = {
                "success": False,
                "summary": str(e),
            }

            self._audit_operation(
                command=command,
                payload=payload,
                result=error_result,
            )

            return error_result

    # ============================================================
    # AUDIT
    # ============================================================
    def _audit_operation(
        self,
        command: str,
        payload: Dict[str, Any],
        result: Dict[str, Any],
    ):
        """
        Persist agent action into Notion Agent Exchange DB.
        Nikad ne smije srušiti glavnu operaciju.
        """
        try:
            db_id = self.db_registry.get("agent_exchange")
            if not db_id:
                return

            summary = result.get("summary", "")
            database_key = payload.get("database_key", "")

            self.notion.pages.create(
                parent={"database_id": db_id},
                properties={
                    "Name": {
                        "title": [
                            {
                                "text": {
                                    "content": f"{command} @ {datetime.utcnow().isoformat()}"
                                }
                            }
                        ]
                    },
                    "Command": {
                        "rich_text": [
                            {"text": {"content": command}}
                        ]
                    },
                    "Database": {
                        "rich_text": [
                            {"text": {"content": str(database_key)}}
                        ]
                    },
                    "Status": {
                        "select": {
                            "name": "SUCCESS" if result.get("success") else "FAILED"
                        }
                    },
                    "Summary": {
                        "rich_text": [
                            {"text": {"content": summary}}
                        ]
                    },
                },
            )
        except Exception:
            # Audit MUST NOT break execution
            pass

    # ============================================================
    # HELPERS
    # ============================================================
    def _get_db_id(self, key: str) -> str:
        db_id = self.db_registry.get(key)
        if not db_id:
            raise ValueError(f"Database key '{key}' nije registrovan.")
        return db_id

    def _extract_titles(self, results: List[Dict[str, Any]]) -> List[str]:
        titles: List[str] = []
        for item in results:
            props = item.get("properties", {})
            for prop in props.values():
                if prop.get("type") == "title":
                    title_items = prop.get("title", [])
                    if title_items:
                        titles.append(title_items[0].get("plain_text", ""))
        return titles

    # ============================================================
    # OPERATIONS
    # ============================================================
    def _query_database(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        db_key = payload.get("database_key")
        if not db_key:
            return {"success": False, "summary": "database_key je obavezan."}

        db_id = self._get_db_id(db_key)
        res = self.notion.databases.query(database_id=db_id)

        results = res.get("results", [])
        titles = self._extract_titles(results)

        return {
            "success": True,
            "summary": f"Pronađeno {len(results)} zapisa.",
            "items": titles,
            "count": len(results),
        }

    def _create_database_entry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        db_key = payload.get("database_key")
        properties = payload.get("properties")

        if not db_key or not properties:
            return {"success": False, "summary": "database_key i properties su obavezni."}

        db_id = self._get_db_id(db_key)

        page = self.notion.pages.create(
            parent={"database_id": db_id},
            properties=properties,
        )

        return {
            "success": True,
            "summary": "Zapis je kreiran.",
            "page_id": page.get("id"),
            "url": page.get("url"),
        }

    def _update_database_entry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        page_id = payload.get("page_id")
        properties = payload.get("properties")

        if not page_id or not properties:
            return {"success": False, "summary": "page_id i properties su obavezni."}

        page = self.notion.pages.update(
            page_id=page_id,
            properties=properties,
        )

        return {
            "success": True,
            "summary": "Zapis je ažuriran.",
            "page_id": page.get("id"),
            "url": page.get("url"),
        }

    def _create_page(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        parent_id = payload.get("parent_page_id")
        properties = payload.get("properties", {})
        children = payload.get("children", [])

        if not parent_id:
            return {"success": False, "summary": "parent_page_id je obavezan."}

        page = self.notion.pages.create(
            parent={"page_id": parent_id},
            properties=properties,
            children=children,
        )

        return {
            "success": True,
            "summary": "Stranica je kreirana.",
            "page_id": page.get("id"),
            "url": page.get("url"),
        }

    def _retrieve_page_content(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        page_id = payload.get("page_id")
        if not page_id:
            return {"success": False, "summary": "page_id je obavezan."}

        blocks = self.notion.blocks.children.list(block_id=page_id)
        count = len(blocks.get("results", []))

        return {
            "success": True,
            "summary": f"Učitano {count} blokova.",
            "count": count,
        }

    def _delete_page(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        page_id = payload.get("page_id")
        if not page_id:
            return {"success": False, "summary": "page_id je obavezan."}

        self.notion.pages.update(page_id=page_id, archived=True)

        return {
            "success": True,
            "summary": "Stranica je arhivirana.",
            "page_id": page_id,
        }
