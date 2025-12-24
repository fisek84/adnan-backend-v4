# services/metrics_persistence_service.py

from __future__ import annotations

from datetime import datetime
import logging
import os
from typing import Any, Dict, List, Optional

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
        self.api_key: Optional[str] = os.getenv("NOTION_API_KEY")
        self.db_id: Optional[str] = os.getenv("NOTION_AGENT_EXCHANGE_DB_ID")

        self.notion: Optional[Client] = (
            Client(auth=self.api_key) if self.api_key else None
        )

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

        counters_raw = snapshot.get("counters") or {}
        counters: Dict[str, Any] = (
            counters_raw if isinstance(counters_raw, dict) else {}
        )

        # Backward/forward compatible handling:
        # - v1 used {"events": {event_type: [...]} }
        # - newer snapshot can provide {"events": [...], "events_by_type": {...}}
        events_by_type_raw = snapshot.get("events_by_type")
        if events_by_type_raw is None:
            events_raw = snapshot.get("events") or {}
            events_by_type: Dict[str, Any] = (
                events_raw if isinstance(events_raw, dict) else {}
            )
        else:
            events_by_type = (
                events_by_type_raw if isinstance(events_by_type_raw, dict) else {}
            )

        summary_lines: List[str] = [f"{k}: {v}" for k, v in counters.items()][
            : self.MAX_SUMMARY_LINES
        ]

        try:
            page = self.notion.pages.create(
                parent={"database_id": self.db_id},
                properties={
                    "Name": {
                        "title": [
                            {
                                "text": {
                                    "content": f"Metrics Snapshot @ {datetime.utcnow().isoformat()}",
                                }
                            }
                        ]
                    },
                    "Command": {
                        "rich_text": [{"text": {"content": "metrics_snapshot"}}]
                    },
                    "Status": {"select": {"name": "SUCCESS"}},
                    "Summary": {
                        "rich_text": [{"text": {"content": "\n".join(summary_lines)}}]
                    },
                },
            )

            return {
                "ok": True,
                "page_id": page.get("id"),
                "counters": len(counters),
                "event_types": len(events_by_type),
            }

        except Exception as e:
            logger.exception("Metrics persistence failed")
            return {
                "ok": False,
                "error": str(e),
            }
