# routers/ceo_console_router.py
from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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

    # CANON: force read_only/propose-only regardless of user-provided flags
    read_only = True
    require_approval = True

    knowledge_payload = bundle.get("knowledge_payload")
    if not isinstance(knowledge_payload, dict):
        knowledge_payload = {}

    agent_input = AgentInput(
        message=req.text,
        snapshot=knowledge_payload,  # SSOT payload to agent
        conversation_id=req.session_id,
        preferred_agent_id=req.preferred_agent_id,
        identity_pack={
            "mode": "ADVISOR",
            "read_only": True,
            "require_approval": True,
        },
        metadata={
            "initiator": initiator,
            "canon": "read_propose_only",
            "router_version": ROUTER_VERSION,
            "endpoint": "/api/internal/ceo-console/command/internal",
            "snapshot_meta": snapshot_meta,
            "read_only": True,
            "require_approval": True,
            # UI/dashboard snapshot stays here (not in agent snapshot)
            "ceo_dashboard_snapshot": bundle.get("ceo_dashboard_snapshot") or {},
            "knowledge_snapshot_meta": bundle.get("knowledge_snapshot_meta") or {},
            "context_hint": req.context_hint or {},
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

    resp = CEOCommandResponse(
        ok=True,
        read_only=read_only,
        summary=_extract_agent_text(agent_out),
        proposed_commands=_extract_proposed_commands_opaque(agent_out),
        context={
            "canon": "read_propose_only",
            "initiator": initiator,
            "snapshot": _redact_snapshot_for_response(bundle),
            "snapshot_meta": snapshot_meta,
            "read_only": read_only,
            "require_approval": require_approval,
        },
        trace={
            "router_version": ROUTER_VERSION,
            "initiator": initiator,
            "knowledge_snapshot_meta": bundle.get("knowledge_snapshot_meta") or {},
        },
    )

    _merge_agent_trace_into_response(resp, agent_out)
    return resp


@router.post("/command")
async def ceo_command_alias(req: CEOCommandRequest = Body(...)) -> CEOCommandResponse:
    return await ceo_command(req)
