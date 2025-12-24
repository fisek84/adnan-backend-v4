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

    violations_raw = alert_result.get("violations", [])
    violations = violations_raw if isinstance(violations_raw, list) else []

    snapshot_alerts_raw = alert_result.get("snapshot", {})
    snapshot_alerts = (
        snapshot_alerts_raw if isinstance(snapshot_alerts_raw, dict) else {}
    )

    # approvals overview treba biti defanzivan (ne pretpostavljamo metodu na servisu)
    approvals_overview: Dict[str, Any]
    if hasattr(approval_service, "get_overview"):
        approvals_overview = approval_service.get_overview()  # type: ignore[attr-defined]
        if not isinstance(approvals_overview, dict):
            approvals_overview = {}
    else:
        # fallback na kanonske metode koje postoje u ApprovalStateService
        pending = approval_service.list_pending()
        approvals_overview = {
            "total": len(approval_service.list_approvals()),
            "pending_count": len(pending),
            "pending": pending,
        }

    csi = conversation_state.get()
    if not isinstance(csi, dict):
        csi = {}

    metrics = MetricsService.snapshot()
    if not isinstance(metrics, dict):
        metrics = {}

    return {
        "ok": ok,
        "violations": violations,
        "snapshot": {
            "alerts": snapshot_alerts,
            "csi": csi,
            "approvals": approvals_overview,
            "metrics": metrics,
        },
        "read_only": True,
    }


# Export alias (da import bude stabilan u gateway_server.py)
alerting_router = router
