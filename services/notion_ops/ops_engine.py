import os
from typing import Dict, Any, List
from notion_client import Client


class NotionOpsEngine:
    """
    NotionOpsEngine — V1.0 OPS REALITY WORKER

    RULES:
    - Executes REAL side-effects
    - Returns MINIMAL OPS RESULT
    - NO lifecycle fields
    - NO execution state
    - NO request / identity awareness
    - Best-effort audit ONLY
    """

    def __init__(self):
        self.notion = Client(auth=os.getenv("NOTION_API_KEY"))

        self.db_registry: Dict[str, str] = {
            "goals": os.getenv("NOTION_GOALS_DB_ID"),
            "tasks": os.getenv("NOTION_TASKS_DB_ID"),
            "projects": os.getenv("NOTION_PROJECTS_DB_ID"),
            "agent_exchange": os.getenv("NOTION_AGENT_EXCHANGE_DB_ID"),
        }

    # ============================================================
    # PUBLIC OPS ENTRYPOINT
    # ============================================================
    async def execute(
        self,
        *,
        command: str,
        payload: Dict[str, Any],
    ) -> Dict[str, Any]:

        try:
            if command == "query_database":
                raw = self._query_database(payload)

            elif command == "create_database_entry":
                raw = self._create_database_entry(payload)

            elif command == "update_database_entry":
                raw = self._update_database_entry(payload)

            elif command == "create_page":
                raw = self._create_page(payload)

            elif command == "retrieve_page_content":
                raw = self._retrieve_page_content(payload)

            elif command == "delete_page":
                raw = self._delete_page(payload)

            else:
                raw = {
                    "success": False,
                    "summary": "Nepoznata Notion operacija.",
                }

            self._audit_operation(command, raw)
            return self._normalize(raw)

        except Exception as e:
            raw = {
                "success": False,
                "summary": str(e),
            }
            self._audit_operation(command, raw)
            return self._normalize(raw)

    # ============================================================
    # NORMALIZATION (OPS CONTRACT)
    # ============================================================
    def _normalize(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "success": bool(raw.get("success")),
            "summary": raw.get("summary", ""),
            "details": raw,
        }

    # ============================================================
    # AUDIT (BEST-EFFORT)
    # ============================================================
    def _audit_operation(self, command: str, result: Dict[str, Any]) -> None:
        try:
            db_id = self.db_registry.get("agent_exchange")
            if not db_id:
                return

            self.notion.pages.create(
                parent={"database_id": db_id},
                properties={
                    "Name": {
                        "title": [
                            {
                                "text": {
                                    "content": f"{command}"
                                }
                            }
                        ]
                    },
                    "Command": {
                        "rich_text": [
                            {"text": {"content": command}}
                        ]
                    },
                    "Status": {
                        "select": {
                            "name": "SUCCESS" if result.get("success") else "FAILED"
                        }
                    },
                    "Summary": {
                        "rich_text": [
                            {"text": {"content": result.get("summary", "")}}
                        ]
                    },
                },
            )
        except Exception:
            pass  # audit must NEVER break ops

    # ============================================================
    # HELPERS / OPERATIONS (UNCHANGED LOGIC)
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

    def _query_database(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        db_key = payload.get("database_key")
        if not db_key:
            return {"success": False, "summary": "database_key je obavezan."}

        res = self.notion.databases.query(database_id=self._get_db_id(db_key))
        results = res.get("results", [])
        return {
            "success": True,
            "summary": f"Pronađeno {len(results)} zapisa.",
            "items": self._extract_titles(results),
            "count": len(results),
        }

    def _create_database_entry(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        db_key = payload.get("database_key")
        properties = payload.get("properties")
        if not db_key or not properties:
            return {"success": False, "summary": "database_key i properties su obavezni."}

        page = self.notion.pages.create(
            parent={"database_id": self._get_db_id(db_key)},
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

        page = self.notion.pages.update(page_id=page_id, properties=properties)
        return {
            "success": True,
            "summary": "Zapis je ažuriran.",
            "page_id": page.get("id"),
            "url": page.get("url"),
        }

    def _create_page(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        parent_id = payload.get("parent_page_id")
        if not parent_id:
            return {"success": False, "summary": "parent_page_id je obavezan."}

        page = self.notion.pages.create(
            parent={"page_id": parent_id},
            properties=payload.get("properties", {}),
            children=payload.get("children", []),
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
        return {
            "success": True,
            "summary": f"Učitano {len(blocks.get('results', []))} blokova.",
            "count": len(blocks.get("results", [])),
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
