# services/notion_ops/ops_validator.py

from typing import Dict, Any
from .ops_engine import NotionOpsEngine


class NotionOpsValidator:
    """
    Validacioni modul za NotionOps.
    Provjerava:
    - da li je DB key validan
    - da li payload ima potrebne parametre
    - sprečava štetu u DB
    """

    REQUIRED_FIELDS = {
        "db.read.all": ["key"],
        "db.read.filtered": ["key", "filter"],
        "db.delete.page": ["page_id"],
        "db.delete.all": ["key"],
        "db.describe": ["key"],
        "db.full_diagnostic": [],
    }

    def __init__(self, engine: NotionOpsEngine):
        self.engine = engine

    # ============================================================
    # PAYLOAD VALIDATION
    # ============================================================

    def validate(self, command: str, payload: Dict[str, Any]):
        # 1 — Validate command exists
        if command not in self.REQUIRED_FIELDS:
            raise ValueError(f"Validator: nepoznata komanda '{command}'")

        # 2 — Required fields check
        missing = []
        for field in self.REQUIRED_FIELDS[command]:
            if field not in payload:
                missing.append(field)

        if missing:
            raise ValueError(
                f"Validator: payload nedostaje polja: {', '.join(missing)}"
            )

        # 3 — Validate DB key if needed
        if "key" in payload:
            key = payload["key"]
            if key not in self.engine.db_registry:
                raise ValueError(
                    f"Validator: DB key '{key}' ne postoji u registry-ju."
                )

        return True
