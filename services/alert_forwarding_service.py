from __future__ import annotations

from datetime import datetime
import logging
import os
from typing import Any, Dict, List, Optional

from notion_client import Client

from services.alerting_service import AlertingService


logger = logging.getLogger(__name__)


class AlertForwardingService:
    """
    Alert Forwarding Service

    RULES:
    - READ alerting status
    - WRITE alerts to external systems
    - NO execution
    - NO decisions
    """

    def __init__(self):
        self.alerting = AlertingService()

        api_key: Optional[str] = os.getenv("NOTION_API_KEY")
        self.db_id: Optional[str] = os.getenv("NOTION_AGENT_EXCHANGE_DB_ID")

        self.notion: Optional[Client] = Client(auth=api_key) if api_key else None

        if not api_key:
            logger.warning("NOTION_API_KEY not set")

        if not self.db_id:
            logger.warning("NOTION_AGENT_EXCHANGE_DB_ID not set")

    # --------------------------------------------------
    # PUBLIC ENTRYPOINT
    # --------------------------------------------------
    def forward_alerts(self) -> Dict[str, Any]:
        alert_status = self.alerting.evaluate()

        if bool(alert_status.get("ok", False)):
            return {
                "forwarded": False,
                "reason": "No active alerts",
                "read_only": True,
            }

        violations_raw = alert_status.get("violations", [])
        violations: List[Dict[str, Any]] = (
            violations_raw if isinstance(violations_raw, list) else []
        )
        if not violations:
            return {
                "forwarded": False,
                "reason": "No violations to forward",
                "read_only": True,
            }

        if not self.notion:
            return {
                "forwarded": False,
                "error": "Notion not configured",
                "read_only": True,
            }

        if not self.db_id:
            return {
                "forwarded": False,
                "error": "Notion DB not configured",
                "read_only": True,
            }

        forwarded: List[Dict[str, Any]] = []

        for v in violations:
            if not isinstance(v, dict):
                continue

            v_type = v.get("type")
            if not isinstance(v_type, str) or not v_type:
                v_type = "unknown"

            try:
                page = self.notion.pages.create(
                    parent={"database_id": self.db_id},
                    properties={
                        "Name": {"title": [{"text": {"content": f"ALERT: {v_type}"}}]},
                        "Command": {"rich_text": [{"text": {"content": "alerting"}}]},
                        "Status": {"select": {"name": "FAILED"}},
                        "Summary": {
                            "rich_text": [
                                {
                                    "text": {
                                        "content": (
                                            f"Violation: {v_type}\n"
                                            f"Value: {v.get('value')}\n"
                                            f"Threshold: {v.get('threshold')}\n"
                                            f"Detected at: {datetime.utcnow().isoformat()}"
                                        )
                                    }
                                }
                            ]
                        },
                    },
                )

                forwarded.append(
                    {
                        "type": v_type,
                        "page_id": page.get("id"),
                    }
                )

            except Exception as e:
                logger.exception("Failed to forward alert %s", v_type)
                forwarded.append(
                    {
                        "type": v_type,
                        "error": str(e),
                    }
                )

        return {
            "forwarded": True,
            "count": len(forwarded),
            "alerts": forwarded,
        }
