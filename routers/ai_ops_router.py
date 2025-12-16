from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import logging

from services.notion_ops.ops_commands import NotionOpsCommands
from services.notion_ops.ops_engine import NotionOpsEngine
from services.notion_ops.ops_validator import NotionOpsValidator
from services.cron_service import CronService
from services.approval_ux_service import ApprovalUXService
from services.approval_delegation_service import ApprovalDelegationService
from services.approval_state_service import get_approval_state
from services.agent_health_service import AgentHealthService


router = APIRouter(prefix="/ai-ops", tags=["AI Ops"])

# ------------------------------------------------------------
# Core singletons (Notion OPS)
# ------------------------------------------------------------
_engine = NotionOpsEngine()
_commands = NotionOpsCommands(_engine)
_validator = NotionOpsValidator(_engine)

# ------------------------------------------------------------
# Approval UX (stateless wrapper)
# ------------------------------------------------------------
_approval_ux = ApprovalUXService()

# ------------------------------------------------------------
# Delegation execution (FAZA 4)
# ------------------------------------------------------------
_delegation_service = ApprovalDelegationService()

# ------------------------------------------------------------
# Agent health (FAZA 6 — READ-ONLY)
# ------------------------------------------------------------
_agent_health = AgentHealthService()

# ------------------------------------------------------------
# Cron service (injected, READ-ONLY)
# ------------------------------------------------------------
_cron_service: CronService | None = None


def set_cron_service(cron_service: CronService) -> None:
    global _cron_service
    _cron_service = cron_service


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ============================================================
# MAIN AI-OPS EXECUTION ENDPOINT
# ============================================================
@router.post("/run")
async def ai_ops_run(body: Dict[str, Any]):
    try:
        command = body.get("command")
        payload = body.get("payload", {})

        if not command:
            raise ValueError("Missing 'command' field.")

        _validator.validate(command, payload)
        result = await _engine.run(command, payload)

        return {
            "ok": True,
            "command": command,
            "payload": payload,
            "result": result,
        }

    except Exception as e:
        raise HTTPException(400, detail=str(e))


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
# APPROVAL OPS (FAZA 3 — UX ONLY)
# ============================================================
@router.get("/approval/pending")
def list_pending():
    approval_state = get_approval_state()
    return {
        "approvals": [
            a for a in approval_state._approvals.values()
            if a.get("status") == "pending"
        ],
        "read_only": True,
    }


@router.post("/approval/approve")
def approve(body: Dict[str, Any]):
    try:
        return _approval_ux.approve(
            approval_id=body["approval_id"],
            approved_by=body.get("actor", "unknown"),
            note=body.get("note"),
        )
    except KeyError:
        raise HTTPException(400, detail="approval_id is required")


@router.post("/approval/reject")
def reject(body: Dict[str, Any]):
    try:
        return _approval_ux.reject(
            approval_id=body["approval_id"],
            rejected_by=body.get("actor", "unknown"),
            note=body.get("note"),
        )
    except KeyError:
        raise HTTPException(400, detail="approval_id is required")


# ============================================================
# DELEGATION EXECUTION (FAZA 4)
# ============================================================
@router.post("/delegate")
async def delegate(body: Dict[str, Any]):
    try:
        approval_id = body["approval_id"]
        agent = body["agent"]
    except KeyError:
        raise HTTPException(400, detail="approval_id and agent are required")

    return await _delegation_service.delegate(
        approval_id=approval_id,
        executor=agent,
    )


# ============================================================
# AGENT HEALTH (FAZA 6 — OBSERVABILITY)
# ============================================================
@router.get("/agents/health")
def agents_health():
    return {
        "agents": _agent_health.snapshot(),
        "read_only": True,
    }


# exported router for main.py
ai_ops_router = router
