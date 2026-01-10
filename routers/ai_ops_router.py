# ruff: noqa: E402
# routers/ai_ops_router.py
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Request

from services.agent_health_service import AgentHealthService
from services.alert_forwarding_service import AlertForwardingService
from services.approval_state_service import get_approval_state
from services.cron_service import CronService
from services.decision_outcome_registry import get_decision_outcome_registry
from services.execution_orchestrator import ExecutionOrchestrator
from services.metrics_persistence_service import MetricsPersistenceService

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# ------------------------------------------------------------
# CANONICAL WRITE GUARDS (runtime reads)
# ------------------------------------------------------------

# CANON: meta/proposal wrapper intents must never be approved/executed.
from models.canon import PROPOSAL_WRAPPER_INTENT


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
# IDempotency cache (prevents double-write on repeated approve calls)
# NOTE:
# - This is process-local (in-memory). It eliminates accidental double-approve
#   in the same running server process.
# - True SSOT idempotency should also be enforced in ApprovalState/Orchestrator,
#   but this router-level guard is the safest minimal fix you asked for.
# ------------------------------------------------------------

_APPROVAL_TO_EXECUTION: Dict[str, str] = {}
_EXECUTION_RESULT_CACHE: Dict[str, Dict[str, Any]] = {}


def _norm_status(v: Any) -> str:
    return (v or "").__str__().strip().lower()


def _try_get_existing_approval(
    approval_state: Any, approval_id: str
) -> Optional[Dict[str, Any]]:
    """
    Best-effort read without assuming an interface.
    If ApprovalState exposes a getter, we use it; otherwise returns None.
    """
    if approval_state is None:
        return None

    # Common method names seen in similar codebases.
    for meth_name in ("get", "read", "get_approval", "read_approval", "lookup"):
        meth = getattr(approval_state, meth_name, None)
        if callable(meth):
            try:
                a = meth(approval_id)
                return a if isinstance(a, dict) else None
            except Exception:
                continue

    return None


def _extract_intent_from_approval(approval: Any) -> Optional[str]:
    """
    Best-effort extraction of intent/command from approval payload_summary, if present.
    This is only a defensive UX error; SSOT fix is in gateway (unwrap before approval creation).
    """
    if not isinstance(approval, dict):
        return None
    ps = approval.get("payload_summary")
    if not isinstance(ps, dict):
        return None
    intent = ps.get("intent") or ps.get("command")
    return intent.strip() if isinstance(intent, str) and intent.strip() else None


def _cached_response_for_approval(approval_id: str) -> Optional[Dict[str, Any]]:
    """
    Return a stable response if we've already executed this approval in this process.
    """
    execution_id = _APPROVAL_TO_EXECUTION.get(approval_id)
    if not execution_id:
        return None
    cached = _EXECUTION_RESULT_CACHE.get(execution_id)
    if isinstance(cached, dict) and cached:
        return cached
    return None


def _cache_execution_result(
    *, approval_id: str, execution_id: str, execution_result: Dict[str, Any]
) -> None:
    _APPROVAL_TO_EXECUTION[approval_id] = execution_id
    _EXECUTION_RESULT_CACHE[execution_id] = execution_result


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

    # PATCH (CANON):
    # Ensure orchestrator uses the same approvals instance used by the router.
    # Prevents edge-case mismatches if approvals injection is not the same object
    # as get_approval_state() return value.
    try:
        setattr(_orchestrator, "approvals", approvals)
    except Exception:
        pass

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
    """
    IMPORTANT FIX:
    - Router-level idempotency guard to prevent repeated /approve calls from re-executing writes.
    - If approval is already approved/completed, return cached result (same process),
      or no-op response without invoking orchestrator.resume().
    - TTL behavior (prod hygiene): if approval is expired, return 410 and do not execute.
    """
    _guard_write(request)

    approval_id = body.get("approval_id")
    if not isinstance(approval_id, str) or not approval_id.strip():
        raise HTTPException(400, detail="approval_id is required")
    approval_id = approval_id.strip()

    # 0) Fast path: if we already completed this approval in this process, return stable result.
    cached = _cached_response_for_approval(approval_id)
    if isinstance(cached, dict) and cached:
        logger.info(
            "ai_ops_router: approve idempotent hit (cached) approval_id=%s", approval_id
        )
        return cached

    approved_by = body.get("approved_by", "unknown")
    note = body.get("note")

    approval_state = _get_approval_state()

    # 1) Best-effort: detect terminal states BEFORE mutating state and BEFORE resuming orchestrator.
    existing = _try_get_existing_approval(approval_state, approval_id)
    if isinstance(existing, dict):
        st = _norm_status(existing.get("status"))

        # TTL: expired approvals are terminal and must not execute.
        if st == "expired":
            raise HTTPException(status_code=410, detail="Approval expired")

        # Treat both "approved" and "completed" as idempotent terminal-ish from router POV.
        if st in ("approved", "completed"):
            execution_id0 = existing.get("execution_id")
            # If we have an execution_id and maybe cached result, return it. Otherwise no-op.
            if isinstance(execution_id0, str) and execution_id0.strip():
                cached2 = _EXECUTION_RESULT_CACHE.get(execution_id0.strip())
                if isinstance(cached2, dict) and cached2:
                    logger.info(
                        "ai_ops_router: approve idempotent hit (existing+cache) approval_id=%s execution_id=%s",
                        approval_id,
                        execution_id0.strip(),
                    )
                    return cached2

            logger.warning(
                "ai_ops_router: approve called again for already-approved approval_id=%s; returning no-op",
                approval_id,
            )
            return {
                "execution_id": existing.get("execution_id"),
                "execution_state": "COMPLETED" if st == "completed" else "APPROVED",
                "result": existing.get("result"),
                "approval": existing,
                "read_only": False,
                "note": "idempotent_noop_already_approved",
            }

        # If already rejected: treat as terminal (do not resume).
        if st == "rejected":
            raise HTTPException(status_code=409, detail="Approval rejected")

        # FIX: if this approval is a proposal wrapper, block BEFORE state mutation.
        intent0 = _extract_intent_from_approval(existing)
        if intent0 == PROPOSAL_WRAPPER_INTENT:
            raise HTTPException(
                status_code=400,
                detail="cannot approve proposal wrapper (ceo.command.propose); unwrap required before approval is created",
            )

    # 2) Approve state transition (first time).
    try:
        approval = approval_state.approve(
            approval_id,
            approved_by=approved_by if isinstance(approved_by, str) else "unknown",
            note=note if isinstance(note, str) else None,
        )

        # DecisionOutcomeRegistry: create decision record at approval-time (best-effort)
        try:
            dor = get_decision_outcome_registry()

            cmd_snapshot = {}
            if isinstance(approval, dict) and isinstance(
                approval.get("payload_summary"), dict
            ):
                cmd_snapshot = approval.get("payload_summary") or {}
            elif isinstance(approval, dict) and isinstance(approval.get("payload_key"), str):
                try:
                    cmd_snapshot = json.loads(approval.get("payload_key") or "{}")
                except Exception:
                    cmd_snapshot = {}

            md = cmd_snapshot.get("metadata") if isinstance(cmd_snapshot, dict) else {}
            md = md if isinstance(md, dict) else {}

            dor.create_or_get_for_approval(
                approval=approval if isinstance(approval, dict) else {},
                cmd_snapshot=cmd_snapshot if isinstance(cmd_snapshot, dict) else {},
                behaviour_mode=md.get("behaviour_mode"),
                alignment_snapshot_hash=md.get("alignment_snapshot_hash"),
                owner=approved_by if isinstance(approved_by, str) else "unknown",
                accepted=True,
            )
        except Exception:
            pass
    except KeyError:
        raise HTTPException(status_code=404, detail="Approval not found")
    except ValueError as e:
        # e.g. ApprovalStateService: "Approval expired"
        raise HTTPException(status_code=410, detail=str(e) or "Approval expired")

    execution_id = approval.get("execution_id") if isinstance(approval, dict) else None
    if not isinstance(execution_id, str) or not execution_id.strip():
        # This should never be "normal": it means /api/execute didn't attach execution_id properly
        raise HTTPException(500, detail="Approval has no execution_id")
    execution_id = execution_id.strip()

    # 4) Defensive: make failure mode explicit instead of a silent 500.
    try:
        orch = _get_orchestrator()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            500, detail=f"Orchestrator init failed: {type(exc).__name__}: {exc}"
        ) from exc

    if orch is None:
        raise HTTPException(500, detail="Orchestrator not initialized")

    # 5) Execute ONCE.
    try:
        execution_result = await orch.resume(execution_id)

        # DecisionOutcomeRegistry: persist execution outcome (best-effort)
        try:
            dor = get_decision_outcome_registry()
            if isinstance(execution_result, dict):
                dor.set_execution_outcome(execution_id=execution_id, outcome=execution_result)
        except Exception:
            pass
    except KeyError as exc:
        # Common case: execution_id not present in orchestrator registry/store.
        raise HTTPException(
            404, detail=f"Execution not found for execution_id={execution_id}"
        ) from exc
    except HTTPException:
        # Do not wrap explicit HTTP errors.
        raise
    except Exception as exc:  # noqa: BLE001
        # Make the root cause visible to happy path scripts/tests.
        raise HTTPException(
            500, detail=f"approve_failed: {type(exc).__name__}: {exc}"
        ) from exc

    # 6) Normalize response shape + cache result to prevent accidental re-run.
    if isinstance(execution_result, dict):
        execution_result.setdefault("approval", approval)
        execution_result.setdefault("read_only", False)

        # Cache by approval_id and execution_id (process-local idempotency).
        _cache_execution_result(
            approval_id=approval_id,
            execution_id=execution_id,
            execution_result=execution_result,
        )

        return execution_result

    # Non-dict execution_result: wrap it, but still cache a stable dict response.
    wrapped = {
        "ok": True,
        "execution_id": execution_id,
        "execution_state": "COMPLETED",
        "execution": execution_result,
        "approval": approval,
        "read_only": False,
    }
    _cache_execution_result(
        approval_id=approval_id, execution_id=execution_id, execution_result=wrapped
    )
    return wrapped


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

        # DecisionOutcomeRegistry: create decision record at reject-time (best-effort)
        try:
            from services.decision_outcome_registry import get_decision_outcome_registry
            import json

            dor = get_decision_outcome_registry()

            cmd_snapshot = {}
            if isinstance(approval, dict) and isinstance(approval.get("payload_summary"), dict):
                cmd_snapshot = approval.get("payload_summary") or {}
            elif isinstance(approval, dict) and isinstance(approval.get("payload_key"), str):
                try:
                    cmd_snapshot = json.loads(approval.get("payload_key") or "{}")
                except Exception:
                    cmd_snapshot = {}

            md = cmd_snapshot.get("metadata") if isinstance(cmd_snapshot, dict) else {}
            md = md if isinstance(md, dict) else {}

            dor.create_or_get_for_approval(
                approval=approval if isinstance(approval, dict) else {},
                cmd_snapshot=cmd_snapshot if isinstance(cmd_snapshot, dict) else {},
                behaviour_mode=md.get("behaviour_mode"),
                alignment_snapshot_hash=md.get("alignment_snapshot_hash"),
                owner=rejected_by if isinstance(rejected_by, str) else "unknown",
                accepted=False,
            )
        except Exception:
            pass
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
