from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from services.alerting_service import AlertingService
from services.approval_state_service import ApprovalStateService
from services.conversation_state_service import ConversationStateService
from services.metrics_service import MetricsService

router = APIRouter(prefix="/alerting", tags=["Alerting"])

alerting_service = AlertingService()
conversation_state = ConversationStateService()
approval_service = ApprovalStateService()


@router.get("/")
def alerting_status() -> Dict[str, Any]:
    """
    READ-ONLY OPS / ADMIN CONSOLE SNAPSHOT

    FAZA 9 / #28

    Returns:
    - alert status
    - violations
    - system snapshot (CSI, approvals, metrics)
    """

    alert_result = alerting_service.evaluate()

    ok = bool(alert_result.get("ok", False))
    violations = alert_result.get("violations", [])
    if not isinstance(violations, list):
        violations = []

    snapshot_alerts = alert_result.get("snapshot", {})
    if not isinstance(snapshot_alerts, dict):
        snapshot_alerts = {}

    return {
        "ok": ok,
        "violations": violations,
        "snapshot": {
            "alerts": snapshot_alerts,
            "csi": conversation_state.get(),
            "approvals": approval_service.get_overview(),
            "metrics": MetricsService.snapshot(),
        },
        "read_only": True,
    }
