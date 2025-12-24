# routers/ai_ops_router.py

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException

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
# CRON OPS
# ============================================================


@router.post("/cron/run")
def cron_run() -> Dict[str, Any]:
    """
    Side effects possible (cron routines).
    """
    if _cron_service is None:
        raise HTTPException(500, detail="CronService not initialized")

    result = _cron_service.run()
    return {
        "ok": True,
        "result": result,
        "read_only": False,
    }


@router.get("/cron/status")
def cron_status() -> Dict[str, Any]:
    if _cron_service is None:
        raise HTTPException(500, detail="CronService not initialized")
    return {
        "ok": True,
        "status": _cron_service.status(),
        "read_only": True,
    }


# ============================================================
# APPROVAL OPS (UX ONLY)
# NOTE: Happy Path test is immutable and calls these endpoints.
# ============================================================


@router.get("/approval/pending")
def list_pending() -> Dict[str, Any]:
    approval_state = get_approval_state()
    return {
        "approvals": approval_state.list_pending(),
        "read_only": True,
    }


@router.post("/approval/approve")
async def approve(body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Approve + resume execution.

    Canon: This is a WRITE path.
    Compatibility: Happy Path sends only approval_id, so approved_by is OPTIONAL here.
    """
    approval_id = body.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id.strip():
        raise HTTPException(400, detail="approval_id is required")

    approved_by = body.get("approved_by", "unknown")
    note = body.get("note")

    # Mark approval as approved (governance write)
    result = _approval_ux.approve(
        approval_id=approval_id.strip(),
        approved_by=approved_by if isinstance(approved_by, str) else "unknown",
        note=note,
    )

    execution_id = result.get("execution_id")
    if not execution_id:
        raise HTTPException(500, detail="Approved approval has no execution_id")

    # RESUME REGISTERED EXECUTION
    execution_result = await _orchestrator.resume(execution_id)

    # IMPORTANT: keep execution_state at top-level (tests expect it).
    if isinstance(execution_result, dict):
        execution_result.setdefault("read_only", False)
        execution_result.setdefault("approval", result)
        return execution_result

    # Fallback (should not happen): wrap, but still mark as write
    return {
        "ok": True,
        "execution": execution_result,
        "approval": result,
        "read_only": False,
    }


@router.post("/approval/reject")
def reject(body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """
    Reject approval (no resume).

    Canon: This is a WRITE path.
    Compatibility: rejected_by is OPTIONAL (fallback unknown).
    """
    approval_id = body.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id.strip():
        raise HTTPException(400, detail="approval_id is required")

    rejected_by = body.get("rejected_by", "unknown")
    note = body.get("note")

    result = _approval_ux.reject(
        approval_id=approval_id.strip(),
        rejected_by=rejected_by if isinstance(rejected_by, str) else "unknown",
        note=note,
    )

    if isinstance(result, dict):
        result.setdefault("read_only", False)
        return result

    return {
        "ok": True,
        "approval": result,
        "read_only": False,
    }


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
    Side-effect: persists metrics snapshot to Notion (if configured).
    """
    result = _metrics_persistence.persist_snapshot()
    return {
        "ok": True,
        "result": result,
        "read_only": False,
    }


# ============================================================
# ALERTS OPS (WRITE TO NOTION)
# ============================================================


@router.post("/alerts/forward")
def forward_alerts() -> Dict[str, Any]:
    """
    Side-effect: forwards alerts to Notion (if configured).
    """
    result = _alert_forwarder.forward_alerts()
    return {
        "ok": True,
        "result": result,
        "read_only": False,
    }


# ============================================================
# EXPORT
# ============================================================

ai_ops_router = router
