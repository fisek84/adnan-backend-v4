from typing import Dict, Any, List
from datetime import datetime
from notion_client import Client


class AgentsService:
    def __init__(self, notion_token: str, exchange_db_id: str, projects_db_id: str):
        self.notion = Client(auth=notion_token)
        self.exchange_db_id = exchange_db_id
        self.projects_db_id = projects_db_id

    # ---------------------------------------------------------
    # 1. POST MESSAGE (Agent Exchange DB)
    # ---------------------------------------------------------
    def post_message(self, agent: str, content: str, msg_type: str = "message") -> Dict[str, Any]:
        title = content[:50]

        page = self.notion.pages.create(
            parent={"database_id": self.exchange_db_id},
            properties={
                "Name": {"title": [{"text": {"content": title}}]},
                "Sender": {"select": {"name": agent}},
                "Recipient": {"select": {"name": "System"}},
                "Content": {"rich_text": [{"text": {"content": content}}]},
                "Timestamp": {"date": {"start": datetime.utcnow().isoformat()}}
            }
        )

        return {"status": "ok", "page_id": page["id"]}

    # ---------------------------------------------------------
    # 2. READ MESSAGES (Agent Exchange DB)
    # ---------------------------------------------------------
    def read_messages(self, limit: int = 20) -> List[Dict[str, Any]]:
        query = self.notion.databases.query(
            database_id=self.exchange_db_id,
            page_size=limit,
            sorts=[{"property": "Timestamp", "direction": "descending"}]
        )
        return query["results"]

    # ---------------------------------------------------------
    # 3. CREATE PROJECT (Projects DB)
    # ---------------------------------------------------------
    def create_project(self, agent: str, project_title: str, description: str = "") -> Dict[str, Any]:
        """
        Koristi stvarne kolone iz Projects DB:
        - Name (title)
        - Agent (select)
        - Description (rich_text)
        - Status (select)
        """

        page = self.notion.pages.create(
            parent={"database_id": self.projects_db_id},
            properties={
                "Name": {"title": [{"text": {"content": project_title}}]},
                "Agent": {"select": {"name": agent}},
                "Description": {"rich_text": [{"text": {"content": description}}]},
                "Status": {"select": {"name": "Active"}}
            }
        )

        return {"status": "ok", "project_id": page["id"]}

    # ---------------------------------------------------------
    # 4. UPDATE AGENT STATE (Agent Exchange DB)
    # ---------------------------------------------------------
    def update_agent_state(self, agent: str, new_state: str) -> Dict[str, Any]:
        title = f"{agent} — state update"

        page = self.notion.pages.create(
            parent={"database_id": self.exchange_db_id},
            properties={
                "Name": {"title": [{"text": {"content": title}}]},
                "Sender": {"select": {"name": agent}},
                "Recipient": {"select": {"name": "System"}},
                "Content": {"rich_text": [{"text": {"content": new_state}}]},
                "Timestamp": {"date": {"start": datetime.utcnow().isoformat()}}
            }
        )

        return {"status": "ok", "state": new_state}