from fastapi import APIRouter
from services.alerting_service import AlertingService
from services.metrics_service import MetricsService
from services.conversation_state_service import ConversationStateService
from services.approval_state_service import ApprovalStateService

router = APIRouter(prefix="/alerting", tags=["Alerting"])

alerting_service = AlertingService()
conversation_state = ConversationStateService()
approval_service = ApprovalStateService()


@router.get("/")
def alerting_status():
    """
    READ-ONLY OPS / ADMIN CONSOLE SNAPSHOT

    FAZA 9 / #28

    Returns:
    - alert status
    - violations
    - system snapshot (CSI, approvals, metrics)
    """

    alert_result = alerting_service.evaluate()

    return {
        "ok": alert_result["ok"],
        "violations": alert_result["violations"],
        "snapshot": {
            "alerts": alert_result.get("snapshot", {}),
            "csi": conversation_state.get(),
            "approvals": approval_service.get_overview(),
            "metrics": MetricsService.snapshot(),
        },
        "read_only": True,
    }
