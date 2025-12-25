from __future__ import annotations

import os
import logging
import hashlib
from datetime import datetime
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Request

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
# CANON TEXT (READ-ONLY)
# ------------------------------------------------------------

CANON_VERSION = "v2"

CANON_TEXT = """CANON — Adnan.AI / Evolia OS (v2)

Adnan.AI is an AI Business Operating System.
It is not a chatbot, assistant, or feature-driven AI.

Fundamental Laws

Initiator ≠ Owner ≠ Executor. This separation is absolute.

READ and WRITE paths are strictly separated.

No execution is allowed without explicit governance approval.

No component may perform implicit actions or side effects.

Every action has a real cost: time, authority, or resources.

Intelligence may advise, but never execute.

Agents execute tasks but never decide or interpret intent.

Workflows orchestrate state transitions, not execution.

UX reflects system truth and never invents state or intent.

If intent is unclear, the system must stop.

If approval is missing, the system must block.

No component may exceed the authority it can control.

No unbounded loops, autonomous escalation, or hidden persistence.

Every decision must be traceable and auditable.

Stability is prioritized over apparent intelligence.

Canonical Regression Guarantee (Happy Path)

The system MUST have a deterministic, executable Happy Path test.

The canonical Happy Path is: Initiator → BLOCKED → APPROVED → EXECUTED.

This path MUST be testable without UI, manually, or interpretation.

The canonical regression test is a CLI-based test (test_happy_path.ps1).

Any change to governance, orchestration, approval, or execution layers
MUST pass the Happy Path test without modification.

If the Happy Path test fails, the change is invalid and MUST be reverted.

The Happy Path test is immutable and may not be adapted to fit new behavior.

The system behavior must adapt to the test, never the test to the system.

Absence of a passing Happy Path test means the system is non-operational.

Design Constraint (Physics Rule)

The system must respect physical constraints
(time, energy, information, authority)
before attempting intelligence or autonomy.

Any violation of this canon invalidates the system design.
"""


def _canon_sha256() -> str:
    return hashlib.sha256(CANON_TEXT.encode("utf-8")).hexdigest()


# ------------------------------------------------------------
# CANONICAL WRITE GUARDS
# ------------------------------------------------------------

def _env_true(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() == "true"


def _ops_safe_mode_enabled() -> bool:
    # Hard block writes when enabled
    return _env_true("OPS_SAFE_MODE", "false")


def _ceo_token_enforcement_enabled() -> bool:
    # Token is enforced ONLY when CEO_TOKEN_ENFORCEMENT=true
    # This keeps immutable happy path working by default.
    return _env_true("CEO_TOKEN_ENFORCEMENT", "false")


def _require_ceo_token_if_enforced(request: Request) -> None:
    """
    Canon: CEO-only writes (optional).
    Compatibility: enforced ONLY when CEO_TOKEN_ENFORCEMENT=true.
    """
    if not _ceo_token_enforcement_enabled():
        return

    expected = os.getenv("CEO_APPROVAL_TOKEN", "").strip()
    if not expected:
        # Fail closed if enforcement is enabled but token isn't configured.
        raise HTTPException(
            status_code=500,
            detail="CEO token enforcement enabled but CEO_APPROVAL_TOKEN is not set",
        )

    provided = (request.headers.get("X-CEO-Token") or "").strip()
    if provided != expected:
        raise HTTPException(status_code=403, detail="CEO token required")


def _guard_write(request: Request) -> None:
    if _ops_safe_mode_enabled():
        raise HTTPException(status_code=403, detail="OPS_SAFE_MODE enabled (writes blocked)")
    _require_ceo_token_if_enforced(request)


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
# CANON (READ-ONLY)
# ============================================================

@router.get("/canon")
def canon() -> Dict[str, Any]:
    return {
        "version": CANON_VERSION,
        "sha256": _canon_sha256(),
        "text": CANON_TEXT,
        "timestamp": datetime.utcnow().isoformat(),
        "read_only": True,
    }


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
# APPROVAL OPS (UX ONLY)
# ============================================================

@router.get("/approval/pending")
def list_pending() -> Dict[str, Any]:
    approval_state = get_approval_state()
    return {"approvals": approval_state.list_pending(), "read_only": True}


@router.post("/approval/approve")
async def approve(request: Request, body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    _guard_write(request)

    approval_id = body.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id.strip():
        raise HTTPException(400, detail="approval_id is required")

    approved_by = body.get("approved_by", "unknown")
    note = body.get("note")

    result = _approval_ux.approve(
        approval_id=approval_id.strip(),
        approved_by=approved_by if isinstance(approved_by, str) else "unknown",
        note=note,
    )

    execution_id = result.get("execution_id")
    if not execution_id:
        raise HTTPException(500, detail="Approved approval has no execution_id")

    execution_result = await _orchestrator.resume(execution_id)

    if isinstance(execution_result, dict):
        execution_result.setdefault("read_only", False)
        execution_result.setdefault("approval", result)
        return execution_result

    return {"ok": True, "execution": execution_result, "approval": result, "read_only": False}


@router.post("/approval/reject")
def reject(request: Request, body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    _guard_write(request)

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

    return {"ok": True, "approval": result, "read_only": False}


# ============================================================
# AGENT HEALTH (READ-ONLY)
# ============================================================

@router.get("/agents/health")
def agents_health() -> Dict[str, Any]:
    return {"agents": _agent_health.snapshot(), "read_only": True}


# ============================================================
# METRICS OPS (WRITE TO NOTION)
# ============================================================

@router.post("/metrics/persist")
def persist_metrics_snapshot(request: Request) -> Dict[str, Any]:
    _guard_write(request)
    result = _metrics_persistence.persist_snapshot()
    return {"ok": True, "result": result, "read_only": False}


# ============================================================
# ALERTS OPS (WRITE TO NOTION)
# ============================================================

@router.post("/alerts/forward")
def forward_alerts(request: Request) -> Dict[str, Any]:
    _guard_write(request)
    result = _alert_forwarder.forward_alerts()
    return {"ok": True, "result": result, "read_only": False}


ai_ops_router = router
