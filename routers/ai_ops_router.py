# routers/ai_ops_router.py

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException

from services.agent_health_service import AgentHealthService
from services.approval_state_service import get_approval_state
from services.approval_ux_service import ApprovalUXService
from services.cron_service import CronService
from services.execution_orchestrator import ExecutionOrchestrator
from services.metrics_persistence_service import MetricsPersistenceService
from services.alert_forwarding_service import AlertForwardingService

router = APIRouter(prefix="/ai-ops", tags=["AI Ops"])

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ------------------------------------------------------------
# SERVICES (CANONICAL)
# ------------------------------------------------------------
_approval_ux = ApprovalUXService()
_orchestrator = ExecutionOrchestrator()
_agent_health = AgentHealthService()

_metrics_persistence = MetricsPersistenceService()
_alert_forwarder = AlertForwardingService()

_cron_service: Optional[CronService] = None


def set_cron_service(cron_service: CronService) -> None:
    global _cron_service
    _cron_service = cron_service


# ============================================================
# CRON OPS (READ-ONLY)
# ============================================================


@router.post("/cron/run")
def cron_run() -> Dict[str, Any]:
    if _cron_service is None:
        raise HTTPException(500, detail="CronService not initialized")
    return _cron_service.run()


@router.get("/cron/status")
def cron_status() -> Dict[str, Any]:
    if _cron_service is None:
        raise HTTPException(500, detail="CronService not initialized")
    return _cron_service.status()


# ============================================================
# APPROVAL OPS (UX ONLY)
# ============================================================


@router.get("/approval/pending")
def list_pending() -> Dict[str, Any]:
    approval_state = get_approval_state()
    return {
        "approvals": approval_state.list_pending(),
        "read_only": True,
    }


@router.post("/approval/approve")
async def approve(body: Dict[str, Any]) -> Dict[str, Any]:
    if "approval_id" not in body:
        raise HTTPException(400, detail="approval_id is required")

    result = _approval_ux.approve(
        approval_id=body["approval_id"],
        approved_by=body.get("approved_by", "unknown"),
        note=body.get("note"),
    )

    execution_id = result.get("execution_id")
    if not execution_id:
        raise HTTPException(500, detail="Approved approval has no execution_id")

    # RESUME REGISTERED EXECUTION
    return await _orchestrator.resume(execution_id)


@router.post("/approval/reject")
def reject(body: Dict[str, Any]) -> Dict[str, Any]:
    if "approval_id" not in body:
        raise HTTPException(400, detail="approval_id is required")

    return _approval_ux.reject(
        approval_id=body["approval_id"],
        rejected_by=body.get("rejected_by", "unknown"),
        note=body.get("note"),
    )


# ============================================================
# AGENT HEALTH (READ-ONLY)
# ============================================================


@router.get("/agents/health")
def agents_health() -> Dict[str, Any]:
    return {
        "agents": _agent_health.snapshot(),
        "read_only": True,
    }


# ============================================================
# METRICS OPS (WRITE TO NOTION)
# ============================================================


@router.post("/metrics/persist")
def persist_metrics_snapshot() -> Dict[str, Any]:
    """
    OPS trigger: persist current metrics snapshot to Notion.

    Side-effect:
    - creates a Notion page (if configured)
    """
    return _metrics_persistence.persist_snapshot()


# ============================================================
# ALERTS OPS (WRITE TO NOTION)
# ============================================================


@router.post("/alerts/forward")
def forward_alerts() -> Dict[str, Any]:
    """
    OPS trigger: forward active alerts to Notion (if configured).

    Side-effect:
    - creates Notion pages (if configured) when violations exist
    """
    return _alert_forwarder.forward_alerts()


# ============================================================
# EXPORT
# ============================================================

ai_ops_router = router
