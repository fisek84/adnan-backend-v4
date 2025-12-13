from typing import Dict, Any, List
from datetime import datetime
import os
import logging

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
        self.notion = Client(auth=os.getenv("NOTION_API_KEY"))
        self.db_id = os.getenv("NOTION_AGENT_EXCHANGE_DB_ID")

        if not self.db_id:
            logger.warning("NOTION_AGENT_EXCHANGE_DB_ID not set")

    # --------------------------------------------------
    # PUBLIC ENTRYPOINT
    # --------------------------------------------------
    def forward_alerts(self) -> Dict[str, Any]:
        alert_status = self.alerting.evaluate()

        if alert_status["ok"]:
            return {
                "forwarded": False,
                "reason": "No active alerts",
            }

        violations = alert_status.get("violations", [])
        if not violations:
            return {
                "forwarded": False,
                "reason": "No violations to forward",
            }

        if not self.db_id:
            return {
                "forwarded": False,
                "error": "Notion DB not configured",
            }

        forwarded = []

        for v in violations:
            try:
                page = self.notion.pages.create(
                    parent={"database_id": self.db_id},
                    properties={
                        "Name": {
                            "title": [
                                {
                                    "text": {
                                        "content": f"ALERT: {v['type']}"
                                    }
                                }
                            ]
                        },
                        "Command": {
                            "rich_text": [
                                {"text": {"content": "alerting"}}
                            ]
                        },
                        "Status": {
                            "select": {"name": "FAILED"}
                        },
                        "Summary": {
                            "rich_text": [
                                {
                                    "text": {
                                        "content": (
                                            f"Violation: {v['type']}\n"
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

                forwarded.append({
                    "type": v["type"],
                    "page_id": page.get("id"),
                })

            except Exception as e:
                logger.exception("Failed to forward alert %s", v["type"])
                forwarded.append({
                    "type": v["type"],
                    "error": str(e),
                })

        return {
            "forwarded": True,
            "count": len(forwarded),
            "alerts": forwarded,
        }
