from __future__ import annotations

import os
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Request

from services.agent_health_service import AgentHealthService
from services.approval_state_service import get_approval_state
from services.cron_service import CronService
from services.execution_orchestrator import ExecutionOrchestrator
from services.metrics_persistence_service import MetricsPersistenceService
from services.alert_forwarding_service import AlertForwardingService

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ------------------------------------------------------------
# CANONICAL WRITE GUARDS
# ------------------------------------------------------------


def _env_true(name: str, default: str = "false") -> bool:
    return (os.getenv(name, default) or "").strip().lower() == "true"


def _ops_safe_mode_enabled() -> bool:
    return _env_true("OPS_SAFE_MODE", "false")


def _ceo_token_enforcement_enabled() -> bool:
    return _env_true("CEO_TOKEN_ENFORCEMENT", "false")


def _require_ceo_token_if_enforced(request: Request) -> None:
    if not _ceo_token_enforcement_enabled():
        return

    expected = (os.getenv("CEO_APPROVAL_TOKEN", "") or "").strip()
    if not expected:
        raise HTTPException(
            status_code=500,
            detail="CEO token enforcement enabled but CEO_APPROVAL_TOKEN is not set",
        )

    provided = (request.headers.get("X-CEO-Token") or "").strip()
    if provided != expected:
        raise HTTPException(status_code=403, detail="CEO token required")


def _guard_write(request: Request) -> None:
    if _ops_safe_mode_enabled():
        raise HTTPException(
            status_code=403, detail="OPS_SAFE_MODE enabled (writes blocked)"
        )
    _require_ceo_token_if_enforced(request)


# ------------------------------------------------------------
# SERVICES (singletons)
# ------------------------------------------------------------
_agent_health = AgentHealthService()
_metrics_persistence = MetricsPersistenceService()
_alert_forwarder = AlertForwardingService()

# Orchestrator internally uses get_approval_state() in its __init__
# so this stays consistent with the canonical approval store.
_orchestrator = ExecutionOrchestrator()

_cron_service: Optional[CronService] = None


def set_cron_service(cron_service: CronService) -> None:
    # app_bootstrap.py očekuje ovu funkciju
    global _cron_service
    _cron_service = cron_service


# ============================================================
# ROUTER
# IMPORTANT:
# gateway_server.py radi include_router(ai_ops_router, prefix="/api")
# zato ovdje prefix mora biti "/ai-ops" (NE "/api/ai-ops")
# ============================================================
router = APIRouter(prefix="/ai-ops", tags=["AI Ops"])


# ============================================================
# CRON OPS
# ============================================================


@router.post("/cron/run")
def cron_run(request: Request) -> Dict[str, Any]:
    _guard_write(request)
    if _cron_service is None:
        raise HTTPException(500, detail="CronService not initialized")
    result = _cron_service.run()
    return {"ok": True, "result": result, "read_only": False}


@router.get("/cron/status")
def cron_status() -> Dict[str, Any]:
    if _cron_service is None:
        raise HTTPException(500, detail="CronService not initialized")
    return {"ok": True, "status": _cron_service.status(), "read_only": True}


# ============================================================
# APPROVAL OPS (Happy Path CONTRACT)
# Test očekuje:
#   GET  /api/ai-ops/approval/pending   -> {"approvals":[...]}, svaki item ima approval_id
#   POST /api/ai-ops/approval/approve   (body: {approval_id: ...}) -> execution_state == "COMPLETED"
# ============================================================


@router.get("/approval/pending")
def list_pending() -> Dict[str, Any]:
    approval_state = get_approval_state()
    pending = approval_state.list_pending()
    # Testu je bitno da je approvals lista i da itemi imaju approval_id.
    return {"approvals": pending, "read_only": True}


@router.post("/approval/approve")
async def approve(request: Request, body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    _guard_write(request)

    approval_id = body.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id.strip():
        raise HTTPException(400, detail="approval_id is required")

    approved_by = body.get("approved_by", "unknown")
    note = body.get("note")

    approval_state = get_approval_state()
    try:
        approval = approval_state.approve(
            approval_id.strip(),
            approved_by=approved_by if isinstance(approved_by, str) else "unknown",
            note=note if isinstance(note, str) else None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Approval not found")

    execution_id = approval.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id.strip():
        raise HTTPException(500, detail="Approval has no execution_id")

    # Resume execution (orchestrator hard-gates approval via ApprovalStateService)
    execution_result = await _orchestrator.resume(execution_id.strip())

    # Test očekuje execution_state na rootu.
    if isinstance(execution_result, dict):
        execution_result.setdefault("approval", approval)
        execution_result.setdefault("read_only", False)
        return execution_result

    return {
        "ok": True,
        "execution": execution_result,
        "approval": approval,
        "read_only": False,
    }


@router.post("/approval/reject")
def reject(request: Request, body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    _guard_write(request)

    approval_id = body.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id.strip():
        raise HTTPException(400, detail="approval_id is required")

    rejected_by = body.get("rejected_by", "unknown")
    note = body.get("note")

    approval_state = get_approval_state()
    try:
        approval = approval_state.reject(
            approval_id.strip(),
            rejected_by=rejected_by if isinstance(rejected_by, str) else "unknown",
            note=note if isinstance(note, str) else None,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Approval not found")

    if isinstance(approval, dict):
        approval.setdefault("read_only", False)
        return approval

    return {"ok": True, "approval": approval, "read_only": False}


# ============================================================
# HEALTH (READ-ONLY)
# ============================================================


@router.get("/agents/health")
def agents_health() -> Dict[str, Any]:
    return {"agents": _agent_health.snapshot(), "read_only": True}


# ============================================================
# METRICS OPS (WRITE)
# ============================================================


@router.post("/metrics/persist")
def persist_metrics_snapshot(request: Request) -> Dict[str, Any]:
    _guard_write(request)
    result = _metrics_persistence.persist_snapshot()
    return {"ok": True, "result": result, "read_only": False}


# ============================================================
# ALERTS OPS (WRITE)
# ============================================================


@router.post("/alerts/forward")
def forward_alerts(request: Request) -> Dict[str, Any]:
    _guard_write(request)
    result = _alert_forwarder.forward_alerts()
    return {"ok": True, "result": result, "read_only": False}


# Export name expected by gateway_server.py
ai_ops_router = router
