from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple, Literal

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

# Pydantic v1/v2 compat for validators
try:
    from pydantic import model_validator  # type: ignore

    _PYDANTIC_V2 = True
except Exception:  # pragma: no cover
    _PYDANTIC_V2 = False
    from pydantic import root_validator  # type: ignore

from models.agent_contract import AgentInput
from services.agent_registry_service import AgentRegistryService
from services.agent_router_service import AgentRouterService
from services.ceo_console_snapshot_service import CEOConsoleSnapshotService
from services.knowledge_snapshot_service import KnowledgeSnapshotService

ROUTER_VERSION = "2026-01-06-canon-read-propose-only-v1"

# IMPORTANT:
# gateway_server.py includes this module with prefix="/api/internal"
# so if router prefix is "/ceo-console", final paths are:
#   POST /api/internal/ceo-console/command
#   POST /api/internal/ceo-console/command/internal
router = APIRouter(prefix="/ceo-console", tags=["CEO Console"])

_agent_registry = AgentRegistryService()
_agent_router = AgentRouterService(_agent_registry)


def _ensure_registry_loaded() -> None:
    try:
        if not _agent_registry.list_agents():
            _agent_registry.load_from_agents_json("config/agents.json", clear=True)
    except Exception:
        pass


# ======================
# MODELS
# ======================


class CEOCommandRequest(BaseModel):
    text: str = Field(..., min_length=1)
    initiator: Optional[str] = None
    session_id: Optional[str] = None
    context_hint: Optional[Dict[str, Any]] = None

    # frontend može poslati, ali router ima pravo override-a
    read_only: Optional[bool] = None
    require_approval: Optional[bool] = None
    preferred_agent_id: Optional[str] = None

    # --- legacy normalization (pydantic v1/v2) ---
    if _PYDANTIC_V2:

        @model_validator(mode="before")  # type: ignore[misc]
        @classmethod
        def _normalize_legacy_payload(cls, values: Any) -> Any:
            if not isinstance(values, dict):
                return values

            md = values.get("metadata")
            if isinstance(md, dict) and not values.get("initiator"):
                ini = md.get("initiator")
                if isinstance(ini, str) and ini.strip():
                    values["initiator"] = ini.strip()

            for k in ("text", "prompt", "input_text", "message"):
                v = values.get(k)
                if isinstance(v, str) and v.strip():
                    values["text"] = v.strip()
                    return values

            data = values.get("data")
            if isinstance(data, dict):
                for k in ("text", "prompt", "input_text", "message"):
                    v = data.get(k)
                    if isinstance(v, str) and v.strip():
                        values["text"] = v.strip()
                        return values

            return values

    else:

        @root_validator(pre=True)  # type: ignore[misc]
        def _normalize_legacy_payload(cls, values: Any) -> Any:
            if not isinstance(values, dict):
                return values

            md = values.get("metadata")
            if isinstance(md, dict) and not values.get("initiator"):
                ini = md.get("initiator")
                if isinstance(ini, str) and ini.strip():
                    values["initiator"] = ini.strip()

            for k in ("text", "prompt", "input_text", "message"):
                v = values.get(k)
                if isinstance(v, str) and v.strip():
                    values["text"] = v.strip()
                    return values

            data = values.get("data")
            if isinstance(data, dict):
                for k in ("text", "prompt", "input_text", "message"):
                    v = data.get(k)
                    if isinstance(v, str) and v.strip():
                        values["text"] = v.strip()
                        return values

            return values


RiskLevel = Literal["low", "medium", "high"]


class CEOCommandResponse(BaseModel):
    ok: bool = True
    read_only: bool = True

    # Human text from agent
    summary: str = ""

    # OPAQUE proposals (must be sent 1:1 to /api/execute/raw by frontend)
    proposed_commands: List[Dict[str, Any]] = Field(default_factory=list)

    # Light context only (no full knowledge payload echo)
    context: Dict[str, Any] = Field(default_factory=dict)

    # Debug/trace
    trace: Dict[str, Any] = Field(default_factory=dict)

    # Confidence & Risk Scoring (VISOK PRIORITET)
    # - Top-level blok za CEO UX (frontend može ignorisati bez regresije)
    confidence_risk: Dict[str, Any] = Field(default_factory=dict)


# ======================
# HELPERS
# ======================


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_dict(v: Any) -> Dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _ensure_list(x: Any) -> List[Any]:
    return x if isinstance(x, list) else []


def _snapshot_meta(wrapper: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    w = wrapper if isinstance(wrapper, dict) else {}
    p = payload if isinstance(payload, dict) else {}
    return {
        "ready": w.get("ready"),
        "last_sync": w.get("last_sync"),
        "payload_keys": sorted(list(p.keys())) if isinstance(p, dict) else [],
        "payload_is_empty": not bool(p) if isinstance(p, dict) else True,
        "wrapper_keys": sorted(list(w.keys())) if isinstance(w, dict) else [],
    }


def _build_snapshot_bundle() -> Dict[str, Any]:
    """
    Bundle za router (UI/debug):
      - ceo_dashboard_snapshot: za frontend
      - knowledge_wrapper: wrapper (ready/last_sync/trace)
      - knowledge_payload: SSOT payload koji IDE AGENTU
      - knowledge_snapshot_meta: mali meta paket
    """
    try:
        ceo_dash = CEOConsoleSnapshotService().snapshot() or {}
    except Exception:
        ceo_dash = {}

    try:
        ks_wrapper = KnowledgeSnapshotService.get_snapshot() or {}
    except Exception:
        ks_wrapper = {}

    try:
        ks_payload = KnowledgeSnapshotService.get_payload() or {}
    except Exception:
        ks_payload = {}

    return {
        "ceo_dashboard_snapshot": ceo_dash,
        "knowledge_wrapper": ks_wrapper,
        "knowledge_payload": ks_payload,  # SSOT for agent
        "knowledge_snapshot_meta": _snapshot_meta(ks_wrapper, ks_payload),
    }


def _redact_snapshot_for_response(bundle: Dict[str, Any]) -> Dict[str, Any]:
    """
    Response context MUST stay light.
    Return dashboard snapshot + meta, but never echo full knowledge payload.
    """
    b = _safe_dict(bundle)
    return {
        "ceo_dashboard_snapshot": _safe_dict(b.get("ceo_dashboard_snapshot")),
        "knowledge_snapshot_meta": _safe_dict(b.get("knowledge_snapshot_meta")),
    }


def _extract_agent_text(agent_out: Any) -> str:
    if isinstance(agent_out, dict):
        t = agent_out.get("text") or agent_out.get("summary")
        return t.strip() if isinstance(t, str) else ""
    t2 = getattr(agent_out, "text", None) or getattr(agent_out, "summary", None)
    return t2.strip() if isinstance(t2, str) else ""


def _extract_proposed_commands_opaque(agent_out: Any) -> List[Dict[str, Any]]:
    """
    CANON: proposed_commands MUST remain opaque payloads (dicts) for /api/execute/raw.
    No remapping to command_type/payload.
    """
    if isinstance(agent_out, dict):
        pcs = agent_out.get("proposed_commands")
    else:
        pcs = getattr(agent_out, "proposed_commands", None)

    out: List[Dict[str, Any]] = []
    for x in _ensure_list(pcs):
        if isinstance(x, dict) and x:
            out.append(x)
    return out


def _merge_agent_trace_into_response(resp: CEOCommandResponse, agent_out: Any) -> None:
    agent_trace: Dict[str, Any] = {}
    agent_id: Optional[str] = None

    if isinstance(agent_out, dict):
        t = agent_out.get("trace")
        if isinstance(t, dict):
            agent_trace = t
        aid = agent_out.get("agent_id")
        if isinstance(aid, str) and aid.strip():
            agent_id = aid.strip()
    else:
        t = getattr(agent_out, "trace", None)
        if isinstance(t, dict):
            agent_trace = t
        aid = getattr(agent_out, "agent_id", None)
        if isinstance(aid, str) and aid.strip():
            agent_id = aid.strip()

    if agent_id:
        resp.trace["agent_id"] = agent_id
    if agent_trace:
        resp.trace.update(agent_trace)


def _extract_alignment_snapshot(
    context_hint: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    SSOT: gateway šalje smart_context kao context_hint.
    Očekujemo: context_hint.alignment_snapshot (dict).
    """
    if not isinstance(context_hint, dict):
        return {}
    a = context_hint.get("alignment_snapshot")
    return a if isinstance(a, dict) else {}


def _fallback_behaviour_mode(alignment_snapshot: Dict[str, Any]) -> str:
    """
    Deterministic fallback (samo ako ceo_behavior_router nije dostupan).
    """
    if not isinstance(alignment_snapshot, dict) or not alignment_snapshot:
        return "advisory"

    risk = alignment_snapshot.get("risk")
    ops = alignment_snapshot.get("ops")
    execution = alignment_snapshot.get("execution")

    risk_score = 0.0
    blocked_writes = False
    flags: List[str] = []

    if isinstance(risk, dict):
        try:
            risk_score = float(risk.get("score") or 0.0)
        except Exception:
            risk_score = 0.0
        blocked_writes = bool(risk.get("blocked_writes") or False)
        fl = risk.get("flags")
        if isinstance(fl, list):
            flags = [str(x) for x in fl if isinstance(x, (str, int, float, bool))]

    incidents_24h = 0
    errors_1h = 0
    if isinstance(ops, dict):
        try:
            incidents_24h = int(ops.get("incidents_24h") or 0)
        except Exception:
            incidents_24h = 0
        try:
            errors_1h = int(ops.get("errors_1h") or 0)
        except Exception:
            errors_1h = 0

    pending_approvals = 0
    failed_24h = 0
    if isinstance(execution, dict):
        try:
            pending_approvals = int(execution.get("pending_approvals") or 0)
        except Exception:
            pending_approvals = 0
        try:
            failed_24h = int(execution.get("failed_24h") or 0)
        except Exception:
            failed_24h = 0

    # Red alert if high risk OR blocked writes OR clear incident pressure
    if (
        blocked_writes
        or risk_score >= 0.9
        or incidents_24h >= 1
        or errors_1h >= 10
        or ("data_loss_risk" in flags)
    ):
        return "red_alert"

    # Executive if elevated risk or approvals/failures exist
    if risk_score >= 0.7 or pending_approvals >= 1 or failed_24h >= 1:
        return "executive"

    # Advisory for moderate risk
    if risk_score >= 0.3:
        return "advisory"

    # Silent for very low risk
    return "silent"


def _select_behaviour_mode(alignment_snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Pokušaj koristiti services/ceo_behavior_router.py bez pretpostavke API-ja.
    Vraća: {"mode": str, "source": str, "applied": bool}
    """
    # Try to import user-provided behaviour router
    try:
        from services import ceo_behavior_router as br  # type: ignore
    except Exception:
        br = None  # type: ignore

    if br is not None:
        # Try a small set of common hook names (no guessing beyond defensive lookup)
        for fn_name in (
            "select_mode",
            "route_mode",
            "compute_mode",
            "compute_behaviour_mode",
            "get_behaviour_mode",
            "decide_mode",
        ):
            fn = getattr(br, fn_name, None)
            if callable(fn):
                try:
                    out = fn(alignment_snapshot)  # type: ignore[misc]
                    if isinstance(out, str) and out.strip():
                        return {
                            "mode": out.strip(),
                            "source": f"ceo_behavior_router.{fn_name}",
                            "applied": True,
                        }
                    if isinstance(out, dict):
                        m = out.get("behaviour_mode") or out.get("mode")
                        if isinstance(m, str) and m.strip():
                            return {
                                "mode": m.strip(),
                                "source": f"ceo_behavior_router.{fn_name}",
                                "applied": True,
                            }
                except Exception:
                    # Fall through to deterministic fallback
                    pass

    # Fallback
    return {
        "mode": _fallback_behaviour_mode(alignment_snapshot),
        "source": "router.fallback",
        "applied": False,
    }


def _enforce_silent_output(summary: str) -> str:
    """
    Router-level guardrail for DoD:
      - CEO Advisor NE govori uvijek
      - CEO Advisor nikad ne "filozofira" u silent/monitor
    """
    s = (summary or "").strip()
    if not s:
        return ""
    # Deterministic shorting: empty output (frontend can render as no-op)
    return ""


def _promote_behaviour_trace(resp: CEOCommandResponse) -> None:
    """
    Test expects resp.trace.behaviour_mode (top-level).
    Agent trace often puts it under trace.executor.behaviour_mode -> promote.
    """
    tr = resp.trace if isinstance(resp.trace, dict) else {}
    if "behaviour_mode" in tr and isinstance(tr.get("behaviour_mode"), str):
        return

    ex = tr.get("executor")
    if isinstance(ex, dict):
        bm = ex.get("behaviour_mode")
        if isinstance(bm, str) and bm.strip():
            tr["behaviour_mode"] = bm.strip()
        bms = ex.get("behaviour_mode_source")
        if isinstance(bms, str) and bms.strip():
            tr.setdefault("behaviour_mode_source", bms.strip())
        bma = ex.get("behaviour_mode_applied")
        if isinstance(bma, bool):
            tr.setdefault("behaviour_mode_applied", bma)

    resp.trace = tr


# -----------------------------
# Confidence & Risk Scoring
# -----------------------------
def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _extract_intent_and_risk_from_proposal(pc: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[bool]]:
    """
    Returns: (intent, risk_hint, requires_approval)
    - intent: prefers args.ai_command.intent
    - risk_hint: pc["risk"] or pc["risk_hint"]
    - requires_approval: pc["requires_approval"] (if present)
    """
    if not isinstance(pc, dict):
        return None, None, None

    requires_approval = pc.get("requires_approval")
    if not isinstance(requires_approval, bool):
        requires_approval = None

    risk_hint = pc.get("risk") or pc.get("risk_hint")
    if isinstance(risk_hint, str):
        risk_hint = risk_hint.strip().upper()
    else:
        risk_hint = None

    intent = None
    args = pc.get("args")
    if isinstance(args, dict):
        ai_cmd = args.get("ai_command")
        if isinstance(ai_cmd, dict):
            v = ai_cmd.get("intent")
            if isinstance(v, str) and v.strip():
                intent = v.strip()

    if intent is None:
        v2 = pc.get("intent")
        if isinstance(v2, str) and v2.strip():
            intent = v2.strip()

    return intent, risk_hint, requires_approval


def _compute_risk_level(proposed: List[Dict[str, Any]]) -> RiskLevel:
    """
    Deterministic:
    - high: any proposal requires approval OR is notion_write OR risk_hint=HIGH
    - medium: any proposal exists with risk_hint=MEDIUM
    - low: otherwise
    """
    has_any = False
    saw_medium = False

    for pc in proposed:
        if not isinstance(pc, dict) or not pc:
            continue
        has_any = True

        cmd = pc.get("command")
        if isinstance(cmd, str) and cmd.strip().lower() == "notion_write":
            return "high"

        intent, risk_hint, requires_approval = _extract_intent_and_risk_from_proposal(pc)

        if requires_approval is True:
            return "high"

        if isinstance(risk_hint, str) and risk_hint == "HIGH":
            return "high"
        if isinstance(risk_hint, str) and risk_hint == "MEDIUM":
            saw_medium = True

        # If we have ai_command intent at all, it's an actionable ops proposal -> treat as high.
        if isinstance(intent, str) and intent.strip():
            return "high"

    if not has_any:
        return "low"
    if saw_medium:
        return "medium"
    return "low"


def _extract_alignment_confidence(trace: Dict[str, Any]) -> Optional[float]:
    """
    Best-effort: OpenAI executor populates trace["alignment_confidence"] sometimes.
    Return float in [0,1] if valid, else None.
    """
    if not isinstance(trace, dict):
        return None
    v = trace.get("alignment_confidence")
    try:
        f = float(v)
    except Exception:
        return None
    if 0.0 <= f <= 1.0:
        return f
    return None


def _compute_confidence_score(*, risk_level: RiskLevel, trace: Dict[str, Any]) -> float:
    base = _extract_alignment_confidence(trace)
    if base is None:
        base = 0.9

    penalty = 0.0
    if risk_level == "medium":
        penalty = 0.2
    elif risk_level == "high":
        penalty = 0.4

    return _clamp01(base - penalty)


def _inject_confidence_risk(resp: CEOCommandResponse) -> None:
    """
    Adds:
      - resp.confidence_risk (top-level)
      - resp.trace["confidence_risk"] mirror (+ assumption_count_source)
    """
    proposed = resp.proposed_commands if isinstance(resp.proposed_commands, list) else []
    risk_level = _compute_risk_level(proposed)
    confidence_score = _compute_confidence_score(risk_level=risk_level, trace=resp.trace)

    # NIJE POZNATO: sistem ne emitira assumptions -> istinito 0 + source marker
    assumption_count = 0
    payload = {
        "confidence_score": float(confidence_score),
        "risk_level": risk_level,
        "assumption_count": int(assumption_count),
    }
    resp.confidence_risk = dict(payload)

    tr = resp.trace if isinstance(resp.trace, dict) else {}
    tr["confidence_risk"] = {
        **payload,
        "assumption_count_source": "not_provided",
    }
    resp.trace = tr


# ======================
# ROUTES
# ======================


@router.post("/command/internal")
async def ceo_command(req: CEOCommandRequest = Body(...)) -> CEOCommandResponse:
    """
    CANON: This endpoint is READ/PROPOSE ONLY.
    - NEVER executes side-effects
    - ALWAYS returns proposals (if agent produced them) as opaque payloads
    """
    _ensure_registry_loaded()

    initiator = (req.initiator or "ceo_dashboard").strip() or "ceo_dashboard"
    bundle = _build_snapshot_bundle()

    snapshot_meta = {
        "source": "CEOConsoleSnapshotService + KnowledgeSnapshotService(SSOT payload)",
        "ts": _now_iso(),
    }

    read_only = True
    require_approval = bool(req.require_approval)

    # Behaviour mode logic
    context_hint = req.context_hint or {}
    alignment_snapshot = _extract_alignment_snapshot(context_hint)
    behaviour = _select_behaviour_mode(alignment_snapshot)
    behaviour_mode = behaviour.get("mode", "advisory").strip()

    agent_input = AgentInput(
        message=req.text,
        snapshot=bundle.get("knowledge_payload", {}),
        conversation_id=req.session_id,
        preferred_agent_id=req.preferred_agent_id,
        identity_pack={
            "mode": "ADVISOR",
            "read_only": True,
            "require_approval": require_approval,
            "behaviour_mode": behaviour_mode,
        },
        metadata={
            "initiator": initiator,
            "canon": "read_propose_only",
            "router_version": ROUTER_VERSION,
            "snapshot_meta": snapshot_meta,
            "read_only": True,
            "require_approval": require_approval,
            "alignment_snapshot": alignment_snapshot,
            "behaviour_mode": behaviour_mode,
        },
    )

    try:
        agent_out = await _maybe_await(_agent_router.route(agent_input))
    except Exception as e:
        agent_out = {
            "text": f"Agent error: {e}",
            "proposed_commands": [],
            "trace": {"error": repr(e), "router": "ceo_console_router"},
            "agent_id": "error",
        }

    proposed = _extract_proposed_commands_opaque(agent_out)
    summary = _extract_agent_text(agent_out)

    if behaviour_mode in {"silent", "monitor"} and len(proposed) == 0:
        summary = _enforce_silent_output(summary)

    resp = CEOCommandResponse(
        ok=True,
        read_only=read_only,
        summary=summary,
        proposed_commands=proposed,
        context={
            "canon": "read_propose_only",
            "initiator": initiator,
            "snapshot": _redact_snapshot_for_response(bundle),
            "snapshot_meta": snapshot_meta,
            "read_only": read_only,
            "require_approval": require_approval,
            "behaviour_mode": behaviour_mode,
        },
        trace={
            "router_version": ROUTER_VERSION,
            "initiator": initiator,
            "knowledge_snapshot_meta": bundle.get("knowledge_snapshot_meta") or {},
            "behaviour_mode": behaviour_mode,
            "behaviour_mode_source": behaviour.get("source"),
        },
    )

    _merge_agent_trace_into_response(resp, agent_out)
    _promote_behaviour_trace(resp)
    _inject_confidence_risk(resp)
    return resp


@router.post("/command")
async def ceo_command_alias(req: CEOCommandRequest = Body(...)) -> CEOCommandResponse:
    return await ceo_command(req)
