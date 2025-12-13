from fastapi import APIRouter
from services.alerting_service import AlertingService

router = APIRouter(prefix="/alerting", tags=["Alerting"])

alerting_service = AlertingService()


@router.get("/")
def alerting_status():
    """
    READ-ONLY Alerting Endpoint

    Returns:
    - ok (bool)
    - violations (list)
    - snapshot summary
    """
    result = alerting_service.evaluate()

    return {
        "ok": result["ok"],
        "violations": result["violations"],
        "snapshot": result.get("snapshot", {}),
    }
