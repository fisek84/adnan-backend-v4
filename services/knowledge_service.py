import json
import os
from typing import Any, Dict, List, Optional


class KnowledgeService:
    def __init__(self, knowledge_path: Optional[str] = None):
        # Default: identity/knowledge.json relative to project root
        self.knowledge_path = knowledge_path or os.getenv(
            "IDENTITY_KNOWLEDGE_PATH",
            os.path.join("identity", "knowledge.json")
        )

    def load(self) -> Dict[str, Any]:
        if not os.path.exists(self.knowledge_path):
            return {"version": "0", "entries": []}

        with open(self.knowledge_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def entries(self) -> List[Dict[str, Any]]:
        data = self.load()
        entries = data.get("entries", [])
        if not isinstance(entries, list):
            return []
        return entries
