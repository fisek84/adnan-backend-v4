# routers/ai_ops_router.py
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
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
# CANONICAL WRITE GUARDS (runtime reads)
# ------------------------------------------------------------


def _env_true(name: str, default: str = "false") -> bool:
    return (os.getenv(name, default) or "").strip().lower() == "true"


def _ops_safe_mode_enabled() -> bool:
    # IMPORTANT: runtime read
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
# APPROVAL STATE (optional injection to avoid singleton mismatch)
# ------------------------------------------------------------

_approval_state_override: Optional[Any] = None


def _get_approval_state() -> Any:
    return _approval_state_override or get_approval_state()


# ------------------------------------------------------------
# AGENT REGISTRY (READ-ONLY INTROSPECTION)
# ------------------------------------------------------------


def _repo_root() -> Path:
    # routers/ai_ops_router.py -> routers -> repo root
    return Path(__file__).resolve().parents[1]


def _agents_registry_path() -> Path:
    """
    SSOT path for registry (agents.json).

    Preferred env:
      - AGENTS_JSON_PATH (canonical elsewhere)
      - AGENTS_REGISTRY_PATH (legacy)
    Default:
      <repo_root>/config/agents.json
    """
    repo_root = _repo_root()

    env_path = (os.getenv("AGENTS_JSON_PATH") or "").strip()
    if not env_path:
        env_path = (os.getenv("AGENTS_REGISTRY_PATH") or "").strip()

    if env_path:
        return Path(env_path).expanduser()

    return repo_root / "config" / "agents.json"


def _load_agents_registry() -> Dict[str, Any]:
    """
    READ-ONLY: Load agents.json for introspection/debugging.
    Must never crash the server; returns error payload on failure.
    """
    p = _agents_registry_path()

    try:
        if not p.exists():
            return {
                "ok": False,
                "error": "agents.json not found",
                "path": str(p),
                "read_only": True,
            }

        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("ok", True)
            data.setdefault("path", str(p))
            data.setdefault("read_only", True)
            return data

        return {
            "ok": True,
            "path": str(p),
            "data": data,
            "read_only": True,
        }
    except Exception as e:  # noqa: BLE001
        return {
            "ok": False,
            "error": f"failed to parse agents.json: {e}",
            "path": str(p),
            "read_only": True,
        }


def _registry_agent_count(reg: Dict[str, Any]) -> int:
    try:
        agents = reg.get("agents")
        if isinstance(agents, list):
            return len(agents)
        return 0
    except Exception:
        return 0


# ------------------------------------------------------------
# SERVICES (singletons)
# ------------------------------------------------------------

_agent_health = AgentHealthService()
_metrics_persistence = MetricsPersistenceService()
_alert_forwarder = AlertForwardingService()
_cron_service: Optional[CronService] = None

# IMPORTANT:
# Do NOT instantiate orchestrator at import time.
# Lazy init prevents mismatch with approval_state singleton / bootstrap order.
_orchestrator: Optional[ExecutionOrchestrator] = None


def _get_orchestrator() -> ExecutionOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ExecutionOrchestrator()
        logger.info("ai_ops_router: ExecutionOrchestrator initialized (lazy)")
    return _orchestrator


def set_cron_service(cron_service: CronService) -> None:
    # app_bootstrap.py expects this function
    global _cron_service
    _cron_service = cron_service


def set_ai_ops_services(*, orchestrator: ExecutionOrchestrator, approvals: Any) -> None:
    """
    Optional injection hook used by gateway_server.py lifespan to ensure:
      - shared orchestrator instance
      - shared approval state instance
    """
    global _orchestrator, _approval_state_override
    _orchestrator = orchestrator
    _approval_state_override = approvals
    logger.info("ai_ops_router: services injected (shared orchestrator/approvals)")


# ============================================================
# ROUTER
# IMPORTANT:
# gateway_server.py does include_router(ai_ops_router, prefix="/api")
# therefore prefix here must be "/ai-ops" (NOT "/api/ai-ops")
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
# Test expects:
#   GET  /api/ai-ops/approval/pending   -> {"approvals":[...]} each item has approval_id
#   POST /api/ai-ops/approval/approve   body {approval_id: "..."} -> execution_state == "COMPLETED"
# ============================================================


@router.get("/approval/pending")
def list_pending() -> Dict[str, Any]:
    approval_state = _get_approval_state()
    pending = approval_state.list_pending()
    return {"approvals": pending, "read_only": True}


@router.post("/approval/approve")
async def approve(request: Request, body: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    _guard_write(request)

    approval_id = body.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id.strip():
        raise HTTPException(400, detail="approval_id is required")

    approved_by = body.get("approved_by", "unknown")
    note = body.get("note")

    approval_state = _get_approval_state()

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
        # This should never be "normal": it means /api/execute didn't attach execution_id properly
        raise HTTPException(500, detail="Approval has no execution_id")

    orch = _get_orchestrator()
    execution_result = await orch.resume(execution_id.strip())

    # Ensure test can read execution_state at root.
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

    approval_state = _get_approval_state()
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
# AGENTS (READ-ONLY)
# ============================================================


@router.get("/agents/registry")
def agents_registry() -> Dict[str, Any]:
    """
    READ-ONLY introspection endpoint for SSOT registry (agents.json).
    Path: /api/ai-ops/agents/registry
    """
    return _load_agents_registry()


@router.get("/agents/health")
def agents_health() -> Dict[str, Any]:
    """
    Runtime health (heartbeats/workers) + registry summary.
    Runtime may be empty if you haven't implemented agent heartbeat registration yet.
    """
    runtime = _agent_health.snapshot()
    reg = _load_agents_registry()

    registry_loaded = not (isinstance(reg, dict) and reg.get("ok") is False)
    registry_count = (
        _registry_agent_count(reg) if registry_loaded and isinstance(reg, dict) else 0
    )

    return {
        "read_only": True,
        "agents": runtime,  # backward compatible key
        "runtime_agents": runtime,
        "runtime_count": len(runtime) if isinstance(runtime, dict) else 0,
        "registry_loaded": registry_loaded,
        "registry_count": registry_count,
        "registry_path": str(_agents_registry_path()),
    }


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
