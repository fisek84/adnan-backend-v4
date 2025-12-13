from fastapi import APIRouter
from services.metrics_service import MetricsService

router = APIRouter(prefix="/metrics", tags=["Metrics"])


@router.get("/")
def metrics_snapshot():
    """
    READ-ONLY Metrics Dashboard Snapshot

    Returns:
    - counters
    - events
    """
    return {
        "ok": True,
        "data": MetricsService.snapshot(),
    }
