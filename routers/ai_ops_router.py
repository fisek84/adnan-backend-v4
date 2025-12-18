# routers/ai_ops_router.py

from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import logging

from services.cron_service import CronService
from services.approval_ux_service import ApprovalUXService
from services.approval_state_service import get_approval_state
from services.execution_registry import ExecutionRegistry
from services.execution_orchestrator import ExecutionOrchestrator
from services.agent_health_service import AgentHealthService

router = APIRouter(prefix="/ai-ops", tags=["AI Ops"])

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ------------------------------------------------------------
# SERVICES (CANONICAL)
# ------------------------------------------------------------
_approval_ux = ApprovalUXService()
_registry = ExecutionRegistry()
_orchestrator = ExecutionOrchestrator()
_agent_health = AgentHealthService()

_cron_service: CronService | None = None


def set_cron_service(cron_service: CronService) -> None:
    global _cron_service
    _cron_service = cron_service


# ============================================================
# CRON OPS (READ-ONLY)
# ============================================================


@router.post("/cron/run")
def cron_run():
    if _cron_service is None:
        raise HTTPException(500, detail="CronService not initialized")
    return _cron_service.run()


@router.get("/cron/status")
def cron_status():
    if _cron_service is None:
        raise HTTPException(500, detail="CronService not initialized")
    return _cron_service.status()


# ============================================================
# APPROVAL OPS (UX ONLY)
# ============================================================


@router.get("/approval/pending")
def list_pending():
    approval_state = get_approval_state()
    return {
        "approvals": [
            a
            for a in approval_state._approvals.values()
            if a.get("status") == "pending"
        ],
        "read_only": True,
    }


@router.post("/approval/approve")
async def approve(body: Dict[str, Any]):
    if "approval_id" not in body:
        raise HTTPException(400, detail="approval_id is required")

    result = _approval_ux.approve(
        approval_id=body["approval_id"],
        approved_by=body.get("approved_by", "unknown"),
        note=body.get("note"),
    )

    execution_id = result.get("execution_id")
    if not execution_id:
        raise HTTPException(
            500, detail="Approved approval has no execution_id"
        )

    # 🔑 RESUME REGISTERED EXECUTION
    return await _orchestrator.resume(execution_id)


@router.post("/approval/reject")
def reject(body: Dict[str, Any]):
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
def agents_health():
    return {
        "agents": _agent_health.snapshot(),
        "read_only": True,
    }


# ============================================================
# EXPORT
# ============================================================

ai_ops_router = router
