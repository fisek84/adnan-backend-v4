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

    def __init__(self):
        self.notion = Client(auth=os.getenv("NOTION_API_KEY"))
        self.db_id = os.getenv("NOTION_AGENT_EXCHANGE_DB_ID")

        if not self.db_id:
            logger.warning("NOTION_AGENT_EXCHANGE_DB_ID not set")

    # --------------------------------------------------
    # MAIN ENTRYPOINT
    # --------------------------------------------------
    def persist_snapshot(self) -> Dict[str, Any]:
        """
        Persist current metrics snapshot to Notion.
        """

        snapshot = MetricsService.snapshot()

        if not self.db_id:
            return {
                "ok": False,
                "error": "Notion DB not configured",
            }

        counters = snapshot.get("counters", {})
        events = snapshot.get("events", {})

        summary_lines = [
            f"{k}: {v}" for k, v in counters.items()
        ]

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
                                    "content": "\n".join(summary_lines[:20])
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
