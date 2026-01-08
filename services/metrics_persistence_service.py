# services/metrics_persistence_service.py

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.metrics_service import MetricsService
from services.notion_service import get_notion_service

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MetricsPersistenceService:
    """
    METRICS PERSISTENCE SERVICE — CANONICAL (WORLD-CLASS)

    Odgovornost:
    - READ-ONLY uzima snapshot iz MetricsService
    - WRITE summary u Notion kroz KANONSKI NotionService
    - NEMA uticaja na runtime tok (best-effort)
    - SIGURNO: nikad ne ruši caller-a

    HARD CANON:
    - nema direktnog notion_client korištenja
    - koristi SSOT NotionService singleton
    """

    MAX_SUMMARY_LINES = 20

    def __init__(self) -> None:
        self.db_key: Optional[str] = (
            os.getenv("NOTION_AGENT_EXCHANGE_DB_KEY")
            or os.getenv("NOTION_AGENT_EXCHANGE_DB_ID")
        )

        if not self.db_key:
            logger.warning(
                "MetricsPersistenceService: NOTION_AGENT_EXCHANGE_DB_KEY/DB_ID not set"
            )

    # --------------------------------------------------
    # MAIN ENTRYPOINT (WRITE — BEST EFFORT)
    # --------------------------------------------------
    def persist_snapshot(self) -> Dict[str, Any]:
        try:
            notion = get_notion_service()
        except Exception as exc:  # noqa: BLE001
            logger.warning("Metrics persistence skipped: NotionService unavailable: %s", exc)
            return {"ok": False, "error": "notion_service_unavailable"}

        if not self.db_key:
            return {"ok": False, "error": "db_key_not_configured"}

        snapshot = MetricsService.snapshot()
        if not isinstance(snapshot, dict):
            return {"ok": False, "error": "invalid_metrics_snapshot"}

        counters_raw = snapshot.get("counters")
        counters: Dict[str, Any] = counters_raw if isinstance(counters_raw, dict) else {}

        events_by_type_raw = snapshot.get("events_by_type")
        if isinstance(events_by_type_raw, dict):
            events_by_type = events_by_type_raw
        else:
            legacy_events = snapshot.get("events")
            events_by_type = legacy_events if isinstance(legacy_events, dict) else {}

        summary_lines: List[str] = [
            f"{k}: {v}" for k, v in counters.items()
        ][: self.MAX_SUMMARY_LINES]

        params: Dict[str, Any] = {
            "db_key": self.db_key,
            "properties": {
                "Name": {
                    "title": [
                        {
                            "text": {
                                "content": f"Metrics Snapshot @ {_utc_now_iso()}",
                            }
                        }
                    ]
                },
                "Command": {
                    "rich_text": [{"text": {"content": "metrics_snapshot"}}]
                },
                "Status": {"select": {"name": "SUCCESS"}},
                "Summary": {
                    "rich_text": [
                        {"text": {"content": "\n".join(summary_lines) or "—"}}
                    ]
                },
            },
        }

        try:
            # NOTE:
            # - koristimo kanonski NotionService intent
            # - Metrics persistence je SYSTEM operacija (approval nije potreban)
            result = notion.execute(
                type(
                    "MetricsCommand",
                    (),
                    {
                        "intent": "create_page",
                        "params": params,
                        "approval_id": "system_metrics_write",
                    },
                )()
            )

            if not isinstance(result, dict):
                return {"ok": False, "error": "invalid_notion_response"}

            return {
                "ok": True,
                "page_id": result.get("notion_page_id"),
                "counters": len(counters),
                "event_types": len(events_by_type),
            }

        except Exception as exc:  # noqa: BLE001
            logger.exception("Metrics persistence failed")
            return {"ok": False, "error": str(exc)}
