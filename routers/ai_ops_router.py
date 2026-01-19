# ruff: noqa: E402
# routers/ai_ops_router.py
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Body, HTTPException, Request

from models.canon import PROPOSAL_WRAPPER_INTENT
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


def _is_ceo_request(request: Request) -> bool:
    """
    Check if the request is from a CEO user.
    CEO users are identified by:
    1. Valid X-CEO-Token header (if CEO_TOKEN_ENFORCEMENT is enabled)
    2. X-Initiator == "ceo_chat" or similar CEO indicators
    """
    # If enforcement is enabled, check for valid token
    if _ceo_token_enforcement_enabled():
        expected = (os.getenv("CEO_APPROVAL_TOKEN", "") or "").strip()
        provided = (request.headers.get("X-CEO-Token") or "").strip()
        if expected and provided == expected:
            return True

    # Check for CEO indicators in request (for non-enforced mode)
    initiator = (request.headers.get("X-Initiator") or "").strip().lower()
    if initiator in ("ceo_chat", "ceo_dashboard", "ceo"):
        return True

    return False


def _guard_write(request: Request) -> None:
    # CEO users bypass OPS_SAFE_MODE restrictions
    if _is_ceo_request(request):
        _require_ceo_token_if_enforced(request)
        return

    # Non-CEO users must pass all checks
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
# ------------------------------------------------------------

_APPROVAL_TO_EXECUTION: Dict[str, str] = {}
_EXECUTION_RESULT_CACHE: Dict[str, Dict[str, Any]] = {}


def _norm_status(v: Any) -> str:
    return (v or "").__str__().strip().lower()


def _try_get_existing_approval(
    approval_state: Any, approval_id: str
) -> Optional[Dict[str, Any]]:
    if approval_state is None:
        return None

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
    if not isinstance(approval, dict):
        return None
    ps = approval.get("payload_summary")
    if not isinstance(ps, dict):
        return None
    intent = ps.get("intent") or ps.get("command")
    return intent.strip() if isinstance(intent, str) and intent.strip() else None


def _cached_response_for_approval(approval_id: str) -> Optional[Dict[str, Any]]:
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
# OUTCOME FEEDBACK LOOP (best-effort hooks)
# ------------------------------------------------------------

_OFL_CRON_JOB_NAME = "outcome_feedback_loop.evaluate_due"
_OFL_DEFAULT_LIMIT = 50


def _schedule_outcome_feedback_reviews(decision_record: Any) -> None:
    try:
        if not isinstance(decision_record, dict) or not decision_record:
            return

        from services.outcome_feedback_loop_service import OutcomeFeedbackLoopService

        OutcomeFeedbackLoopService().schedule_reviews_for_decision(
            decision_record=decision_record
        )
    except Exception:
        return


def _sync_ofl_execution_outcome_from_dor_record(dor_record: Any) -> None:
    """
    Best-effort: after execution finishes, sync OFL rows (executed/execution_result)
    using decision_id from DOR record.
    """
    try:
        if not isinstance(dor_record, dict) or not dor_record:
            return

        decision_id = dor_record.get("decision_id")
        executed = dor_record.get("executed")
        execution_result = dor_record.get("execution_result")

        if not isinstance(decision_id, str) or not decision_id.strip():
            return
        if not isinstance(executed, bool):
            return

        from services.outcome_feedback_loop_service import OutcomeFeedbackLoopService

        svc = OutcomeFeedbackLoopService()
        meth = getattr(svc, "update_execution_outcome_for_decision", None)
        if callable(meth):
            meth(
                decision_id=decision_id.strip(),
                executed=bool(executed),
                execution_result=(
                    str(execution_result) if execution_result is not None else None
                ),
            )
    except Exception:
        return


def _cron_job_outcome_feedback_loop_evaluate_due() -> Dict[str, Any]:
    try:
        from services.outcome_feedback_loop_service import OutcomeFeedbackLoopService

        raw = (os.getenv("OUTCOME_FEEDBACK_LOOP_CRON_LIMIT") or "").strip()
        limit = int(raw) if raw.isdigit() else _OFL_DEFAULT_LIMIT

        return OutcomeFeedbackLoopService().evaluate_due_reviews(limit=limit)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _enrich_decision_record_with_snapshots(
    decision_record: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Deterministički, best-effort enrich:
      - alignment_before: CEOAlignmentEngine(identity_pack, world_state_snapshot)
      - kpi_before: world_state_snapshot["kpis"] (canonical per services/world_state_engine.py)

    Ne smije bacati exception (router-level fail-soft).
    """
    if not isinstance(decision_record, dict) or not decision_record:
        return decision_record

    try:
        from services.ceo_alignment_engine import CEOAlignmentEngine
        from services.identity_loader import load_ceo_identity_pack
        from services.world_state_engine import WorldStateEngine

        identity_pack = load_ceo_identity_pack()
        world_state_snapshot = WorldStateEngine().build_snapshot()
        alignment_before = CEOAlignmentEngine().evaluate(
            identity_pack, world_state_snapshot
        )

        kpi_before = None
        kpi_note = "kpis_missing_or_not_dict"
        if isinstance(world_state_snapshot, dict) and isinstance(
            world_state_snapshot.get("kpis"), dict
        ):
            kpi_before = world_state_snapshot.get("kpis")
            kpi_note = "kpis_from_world_state.kpis"
        elif not isinstance(world_state_snapshot, dict):
            kpi_note = "world_state_snapshot_not_dict"

        enriched = dict(decision_record)
        enriched["alignment_before"] = (
            alignment_before
            if isinstance(alignment_before, dict)
            else {"note": "alignment_before_not_dict"}
        )
        enriched["kpi_before"] = (
            kpi_before
            if isinstance(kpi_before, dict)
            else {"note": kpi_note, "kpis": None}
        )
        return enriched
    except Exception:
        return decision_record


# ------------------------------------------------------------
# AGENT REGISTRY (READ-ONLY INTROSPECTION)
# ------------------------------------------------------------


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _agents_registry_path() -> Path:
    repo_root = _repo_root()

    env_path = (os.getenv("AGENTS_JSON_PATH") or "").strip()
    if not env_path:
        env_path = (os.getenv("AGENTS_REGISTRY_PATH") or "").strip()

    if env_path:
        return Path(env_path).expanduser()

    return repo_root / "config" / "agents.json"


def _load_agents_registry() -> Dict[str, Any]:
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

_orchestrator: Optional[ExecutionOrchestrator] = None


def _get_orchestrator() -> ExecutionOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = ExecutionOrchestrator()
        logger.info("ai_ops_router: ExecutionOrchestrator initialized (lazy)")
    return _orchestrator


def set_cron_service(cron_service: CronService) -> None:
    global _cron_service
    _cron_service = cron_service

    try:
        if _cron_service is not None:
            _cron_service.register(
                _OFL_CRON_JOB_NAME, _cron_job_outcome_feedback_loop_evaluate_due
            )
    except Exception:
        pass


def set_ai_ops_services(*, orchestrator: ExecutionOrchestrator, approvals: Any) -> None:
    global _orchestrator, _approval_state_override
    _orchestrator = orchestrator
    _approval_state_override = approvals

    try:
        setattr(_orchestrator, "approvals", approvals)
    except Exception:
        pass

    logger.info("ai_ops_router: services injected (shared orchestrator/approvals)")


router = APIRouter(prefix="/ai-ops", tags=["AI Ops"])


def _extract_notion_links_from_execution_result(
    execution_result: Dict[str, Any],
) -> Dict[str, Any]:
    """Best-effort extraction of Notion URLs from execution results.

    Supports:
      - single create/update/delete results where url lives under result.result.url
      - batch_request where per-op url lives under result.result.operations[].result.result.url

    Returns:
      {"type": "single"|"batch", "links": [{op_id?, intent?, url, page_id?}, ...], "by_op_id": {...}}
    """
    out: Dict[str, Any] = {"type": None, "links": [], "by_op_id": {}}
    if not isinstance(execution_result, dict):
        return out

    wrapper = execution_result.get("result")
    if not isinstance(wrapper, dict):
        wrapper = {}

    payload = wrapper.get("result")
    if not isinstance(payload, dict):
        payload = {}

    intent = payload.get("intent")
    intent = intent if isinstance(intent, str) else ""

    # Batch: payload.operations[]
    if intent in {"batch_request", "batch", "branch_request"}:
        ops = payload.get("operations")
        if isinstance(ops, list) and ops:
            out["type"] = "batch"
            for op in ops:
                if not isinstance(op, dict):
                    continue

                op_id = op.get("op_id")
                op_id = (
                    op_id.strip() if isinstance(op_id, str) and op_id.strip() else None
                )

                op_intent = op.get("intent")
                op_intent = (
                    op_intent.strip()
                    if isinstance(op_intent, str) and op_intent.strip()
                    else None
                )

                page_id = op.get("page_id")
                page_id = (
                    page_id.strip()
                    if isinstance(page_id, str) and page_id.strip()
                    else None
                )

                # sub result nesting: op.result.result.url
                url = None
                sub = op.get("result")
                if isinstance(sub, dict):
                    sub_payload = sub.get("result")
                    if isinstance(sub_payload, dict):
                        u = sub_payload.get("url") or sub_payload.get("notion_url")
                        if isinstance(u, str) and u.strip():
                            url = u.strip()
                        if not page_id:
                            pid = sub_payload.get("page_id") or sub_payload.get("id")
                            if isinstance(pid, str) and pid.strip():
                                page_id = pid.strip()

                if isinstance(url, str) and url.strip():
                    rec = {
                        "url": url,
                        "page_id": page_id,
                        "op_id": op_id,
                        "intent": op_intent,
                    }
                    out["links"].append(rec)
                    if op_id:
                        out["by_op_id"][op_id] = url

            return out

    # Single: payload.url
    url = payload.get("url") or payload.get("notion_url")
    if isinstance(url, str) and url.strip():
        out["type"] = "single"
        page_id = payload.get("page_id") or payload.get("id")
        page_id = (
            page_id.strip() if isinstance(page_id, str) and page_id.strip() else None
        )
        out["links"].append(
            {"url": url.strip(), "page_id": page_id, "intent": intent or None}
        )

    return out


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
    approval_id = approval_id.strip()

    cached = _cached_response_for_approval(approval_id)
    if isinstance(cached, dict) and cached:
        logger.info(
            "ai_ops_router: approve idempotent hit (cached) approval_id=%s", approval_id
        )
        return cached

    approved_by = body.get("approved_by", "unknown")
    note = body.get("note")

    approval_state = _get_approval_state()

    existing = _try_get_existing_approval(approval_state, approval_id)
    if isinstance(existing, dict):
        st = _norm_status(existing.get("status"))

        if st == "expired":
            raise HTTPException(status_code=410, detail="Approval expired")

        if st in ("approved", "completed"):
            execution_id0 = existing.get("execution_id")
            if isinstance(execution_id0, str) and execution_id0.strip():
                # Best-effort OFL sync even on idempotent path
                try:
                    dor0 = get_decision_outcome_registry()
                    dor_rec0 = dor0.get_by_execution_id(execution_id0.strip())
                    _sync_ofl_execution_outcome_from_dor_record(dor_rec0)
                except Exception:
                    pass

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

        if st == "rejected":
            raise HTTPException(status_code=409, detail="Approval rejected")

        intent0 = _extract_intent_from_approval(existing)
        if intent0 == PROPOSAL_WRAPPER_INTENT:
            raise HTTPException(
                status_code=400,
                detail="cannot approve proposal wrapper (ceo.command.propose); unwrap required before approval is created",
            )

    try:
        approval = approval_state.approve(
            approval_id,
            approved_by=approved_by if isinstance(approved_by, str) else "unknown",
            note=note if isinstance(note, str) else None,
        )

        # DecisionOutcomeRegistry: create decision record at approval-time (best-effort)
        try:
            dor = get_decision_outcome_registry()

            cmd_snapshot: Dict[str, Any] = {}
            if isinstance(approval, dict) and isinstance(
                approval.get("payload_summary"), dict
            ):
                cmd_snapshot = approval.get("payload_summary") or {}
            elif isinstance(approval, dict) and isinstance(
                approval.get("payload_key"), str
            ):
                try:
                    cmd_snapshot = json.loads(approval.get("payload_key") or "{}")
                except Exception:
                    cmd_snapshot = {}

            md = cmd_snapshot.get("metadata") if isinstance(cmd_snapshot, dict) else {}
            md = md if isinstance(md, dict) else {}

            decision_record = dor.create_or_get_for_approval(
                approval=approval if isinstance(approval, dict) else {},
                cmd_snapshot=cmd_snapshot if isinstance(cmd_snapshot, dict) else {},
                behaviour_mode=md.get("behaviour_mode"),
                alignment_snapshot_hash=md.get("alignment_snapshot_hash"),
                owner=approved_by if isinstance(approved_by, str) else "unknown",
                accepted=True,
            )

            decision_record = _enrich_decision_record_with_snapshots(decision_record)
            _schedule_outcome_feedback_reviews(decision_record)
        except Exception:
            pass
    except KeyError:
        raise HTTPException(status_code=404, detail="Approval not found")
    except ValueError as e:
        raise HTTPException(status_code=410, detail=str(e) or "Approval expired")

    execution_id = approval.get("execution_id") if isinstance(approval, dict) else None
    if not isinstance(execution_id, str) or not execution_id.strip():
        raise HTTPException(500, detail="Approval has no execution_id")
    execution_id = execution_id.strip()

    try:
        orch = _get_orchestrator()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            500, detail=f"Orchestrator init failed: {type(exc).__name__}: {exc}"
        ) from exc

    if orch is None:
        raise HTTPException(500, detail="Orchestrator not initialized")

    try:
        execution_result = await orch.resume(execution_id)

        # DOR + OFL sync at execution completion (best-effort)
        try:
            dor = get_decision_outcome_registry()
            if isinstance(execution_result, dict):
                updated = dor.set_execution_outcome(
                    execution_id=execution_id, outcome=execution_result
                )
                _sync_ofl_execution_outcome_from_dor_record(updated)
        except Exception:
            pass
    except KeyError as exc:
        raise HTTPException(
            404, detail=f"Execution not found for execution_id={execution_id}"
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            500, detail=f"approve_failed: {type(exc).__name__}: {exc}"
        ) from exc

    if isinstance(execution_result, dict):
        execution_result.setdefault("approval", approval)
        execution_result.setdefault("read_only", False)

        # Best-effort: surface Notion URLs (single + batch) for UI.
        try:
            links = _extract_notion_links_from_execution_result(execution_result)
            if isinstance(links, dict):
                by_op = (
                    links.get("by_op_id")
                    if isinstance(links.get("by_op_id"), dict)
                    else {}
                )
                lst = links.get("links") if isinstance(links.get("links"), list) else []

                if by_op:
                    execution_result.setdefault("notion_urls_by_op_id", by_op)
                if lst:
                    execution_result.setdefault("notion_urls", lst)

                # If backend didn't already provide a user-facing message, provide one.
                existing_text = execution_result.get("text")
                if (
                    not isinstance(existing_text, str) or not existing_text.strip()
                ) and lst:
                    lines = []
                    state = execution_result.get("execution_state")
                    if isinstance(state, str) and state.strip():
                        lines.append(f"Execution: {state.strip()}")
                    else:
                        lines.append("Execution completed")

                    lines.append("")
                    lines.append("Created in Notion:")
                    for rec in lst:
                        if not isinstance(rec, dict):
                            continue
                        u = rec.get("url")
                        if not isinstance(u, str) or not u.strip():
                            continue
                        oid = rec.get("op_id")
                        it = rec.get("intent")
                        label = None
                        if isinstance(oid, str) and oid.strip():
                            label = oid.strip()
                        if isinstance(it, str) and it.strip():
                            label = f"{label} ({it.strip()})" if label else it.strip()
                        if label:
                            lines.append(f"- {label}: {u.strip()}")
                        else:
                            lines.append(f"- {u.strip()}")

                    execution_result["text"] = "\n".join(lines).strip()
        except Exception:
            pass

        _cache_execution_result(
            approval_id=approval_id,
            execution_id=execution_id,
            execution_result=execution_result,
        )

        return execution_result

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

        # DecisionOutcomeRegistry + OFL scheduling at reject-time (best-effort)
        try:
            dor = get_decision_outcome_registry()

            cmd_snapshot: Dict[str, Any] = {}
            if isinstance(approval, dict) and isinstance(
                approval.get("payload_summary"), dict
            ):
                cmd_snapshot = approval.get("payload_summary") or {}
            elif isinstance(approval, dict) and isinstance(
                approval.get("payload_key"), str
            ):
                try:
                    cmd_snapshot = json.loads(approval.get("payload_key") or "{}")
                except Exception:
                    cmd_snapshot = {}

            md = cmd_snapshot.get("metadata") if isinstance(cmd_snapshot, dict) else {}
            md = md if isinstance(md, dict) else {}

            decision_record = dor.create_or_get_for_approval(
                approval=approval if isinstance(approval, dict) else {},
                cmd_snapshot=cmd_snapshot if isinstance(cmd_snapshot, dict) else {},
                behaviour_mode=md.get("behaviour_mode"),
                alignment_snapshot_hash=md.get("alignment_snapshot_hash"),
                owner=rejected_by if isinstance(rejected_by, str) else "unknown",
                accepted=False,
            )

            decision_record = _enrich_decision_record_with_snapshots(decision_record)
            _schedule_outcome_feedback_reviews(decision_record)
        except Exception:
            pass
    except KeyError:
        raise HTTPException(status_code=404, detail="Approval not found")

    if isinstance(approval, dict):
        approval.setdefault("read_only", False)
        return approval

    return {"ok": True, "approval": approval, "read_only": False}


@router.get("/agents/registry")
def agents_registry() -> Dict[str, Any]:
    return _load_agents_registry()


@router.get("/agents/health")
def agents_health() -> Dict[str, Any]:
    runtime = _agent_health.snapshot()
    reg = _load_agents_registry()

    registry_loaded = not (isinstance(reg, dict) and reg.get("ok") is False)
    registry_count = (
        _registry_agent_count(reg) if registry_loaded and isinstance(reg, dict) else 0
    )

    return {
        "read_only": True,
        "agents": runtime,
        "runtime_agents": runtime,
        "runtime_count": len(runtime) if isinstance(runtime, dict) else 0,
        "registry_loaded": registry_loaded,
        "registry_count": registry_count,
        "registry_path": str(_agents_registry_path()),
    }


@router.post("/metrics/persist")
def persist_metrics_snapshot(request: Request) -> Dict[str, Any]:
    _guard_write(request)
    result = _metrics_persistence.persist_snapshot()
    return {"ok": True, "result": result, "read_only": False}


@router.post("/alerts/forward")
def forward_alerts(request: Request) -> Dict[str, Any]:
    _guard_write(request)
    result = _alert_forwarder.forward_alerts()
    return {"ok": True, "result": result, "read_only": False}


ai_ops_router = router
