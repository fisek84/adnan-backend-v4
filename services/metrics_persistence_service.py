# services/metrics_persistence_service.py

from typing import Dict, Any
from datetime import datetime
import os
import logging

from notion_client import Client
from services.metrics_service import MetricsService


logger = logging.getLogger(__name__)


class MetricsPersistenceService:
    """
    Metrics → Notion Persistence

    RULES:
    - READ metrics snapshot
    - WRITE summary to Notion
    - NO influence on runtime flow
    """

    MAX_SUMMARY_LINES = 20

    def __init__(self):
        self.api_key = os.getenv("NOTION_API_KEY")
        self.db_id = os.getenv("NOTION_AGENT_EXCHANGE_DB_ID")

        self.notion = Client(auth=self.api_key) if self.api_key else None

        if not self.api_key:
            logger.warning("NOTION_API_KEY not set")

        if not self.db_id:
            logger.warning("NOTION_AGENT_EXCHANGE_DB_ID not set")

    # --------------------------------------------------
    # MAIN ENTRYPOINT
    # --------------------------------------------------
    def persist_snapshot(self) -> Dict[str, Any]:
        if not self.notion or not self.db_id:
            return {
                "ok": False,
                "error": "Notion not configured",
            }

        snapshot = MetricsService.snapshot()
        counters = snapshot.get("counters") or {}
        events = snapshot.get("events") or {}

        if not isinstance(counters, dict):
            counters = {}
        if not isinstance(events, dict):
            events = {}

        summary_lines = [
            f"{k}: {v}" for k, v in counters.items()
        ][:self.MAX_SUMMARY_LINES]

        try:
            page = self.notion.pages.create(
                parent={"database_id": self.db_id},
                properties={
                    "Name": {
                        "title": [
                            {
                                "text": {
                                    "content": f"Metrics Snapshot @ {datetime.utcnow().isoformat()}"
                                }
                            }
                        ]
                    },
                    "Command": {
                        "rich_text": [
                            {"text": {"content": "metrics_snapshot"}}
                        ]
                    },
                    "Status": {
                        "select": {"name": "SUCCESS"}
                    },
                    "Summary": {
                        "rich_text": [
                            {
                                "text": {
                                    "content": "\n".join(summary_lines)
                                }
                            }
                        ]
                    },
                },
            )

            return {
                "ok": True,
                "page_id": page.get("id"),
                "counters": len(counters),
                "event_types": len(events),
            }

        except Exception as e:
            logger.exception("Metrics persistence failed")
            return {
                "ok": False,
                "error": str(e),
            }
