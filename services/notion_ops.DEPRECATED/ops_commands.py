# services/notion_ops/ops_commands.py

from typing import Dict, Any
from .ops_engine import NotionOpsEngine


class NotionOpsCommands:
    """
    Komandni sloj za NotionOpsEngine.
    Ovdje definišemo sve operacije koje AI agent može da pozove.
    """

    def __init__(self, engine: NotionOpsEngine):
        self.engine = engine

        # Registry svih komandi i njihovih handlera
        self.commands = {
            "db.read.all": self.read_all,
            "db.read.filtered": self.read_filtered,
            "db.delete.page": self.delete_page,
            "db.delete.all": self.delete_all,
            "db.describe": self.describe,
            "db.full_diagnostic": self.full_diagnostic,
        }

    # ============================================================
    # MAIN EXECUTOR
    # ============================================================

    def execute(self, command: str, payload: Dict[str, Any]):
        if command not in self.commands:
            raise ValueError(f"Nepoznata komanda: {command}")
        return self.commands[command](payload)

    # ============================================================
    # COMMAND HANDLERS
    # ============================================================

    def read_all(self, payload: Dict[str, Any]):
        key = payload.get("key")
        return self.engine.read_all(key)

    def read_filtered(self, payload: Dict[str, Any]):
        key = payload.get("key")
        filter_payload = payload.get("filter")
        return self.engine.read_filtered(key, filter_payload)

    def delete_page(self, payload: Dict[str, Any]):
        page_id = payload.get("page_id")
        return self.engine.delete_page(page_id)

    def delete_all(self, payload: Dict[str, Any]):
        key = payload.get("key")
        return self.engine.delete_all(key)

    def describe(self, payload: Dict[str, Any]):
        key = payload.get("key")
        return self.engine.describe_db(key)

    def full_diagnostic(self, payload: Dict[str, Any]):
        return self.engine.full_diagnostic()
