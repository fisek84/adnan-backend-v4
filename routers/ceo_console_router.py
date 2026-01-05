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
from services.intent_mode_service import decide_read_write  # KLJUČNO

ROUTER_VERSION = "2026-01-03-ssot-snapshot-payload-v3"

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


class ProposedAICommand(BaseModel):
    command_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    status: str = "BLOCKED"
    required_approval: bool = True
    cost_hint: Optional[str] = None
    risk_hint: Optional[str] = None


class CEOCommandResponse(BaseModel):
    ok: bool = True
    read_only: bool = False
    context: Dict[str, Any] = Field(default_factory=dict)
    summary: str = ""
    questions: List[str] = Field(default_factory=list)
    plan: List[str] = Field(default_factory=list)
    options: List[str] = Field(default_factory=list)
    proposed_commands: List[ProposedAICommand] = Field(default_factory=list)
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


def _snapshot_meta(wrapper: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    # meta must be stable and small
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
    # CEO dashboard snapshot (UI context)
    try:
        ceo_dash = CEOConsoleSnapshotService().snapshot() or {}
    except Exception:
        ceo_dash = {}

    # Knowledge snapshot wrapper + payload
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
        "knowledge_payload": ks_payload,  # IMPORTANT: SSOT for agent
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


def _coerce_proposed_commands(agent_output: Any) -> List[ProposedAICommand]:
    """
    Accept ProposedCommand as:
      - dict
      - pydantic model / object with .command/.args/.requires_approval/.risk
    """
    out: List[ProposedAICommand] = []

    # Get proposed_commands from AgentOutput or dict
    if isinstance(agent_output, dict):
        pcs = agent_output.get("proposed_commands")
    else:
        pcs = getattr(agent_output, "proposed_commands", None)

    if not isinstance(pcs, list):
        return out

    for pc in pcs:
        cmd = None
        args: Dict[str, Any] = {}
        requires_approval = True
        risk: Optional[str] = None
        status = "BLOCKED"

        # dict path
        if isinstance(pc, dict):
            cmd = pc.get("command") or pc.get("command_type") or pc.get("type")

            a0 = pc.get("args")
            if isinstance(a0, dict):
                args = a0
            else:
                p0 = pc.get("payload")
                args = p0 if isinstance(p0, dict) else {}

            ra = pc.get("requires_approval")
            if ra is not None:
                requires_approval = bool(ra)

            r0 = pc.get("risk") or pc.get("risk_hint")
            risk = str(r0) if r0 is not None else None

            st0 = pc.get("status")
            status = str(st0) if st0 is not None else status

        # object / pydantic path
        else:
            cmd = (
                getattr(pc, "command", None)
                or getattr(pc, "command_type", None)
                or getattr(pc, "type", None)
            )

            a1 = getattr(pc, "args", None)
            if isinstance(a1, dict):
                args = a1
            else:
                p1 = getattr(pc, "payload", None)
                args = p1 if isinstance(p1, dict) else {}

            ra1 = getattr(pc, "requires_approval", None)
            if ra1 is not None:
                requires_approval = bool(ra1)

            r1 = getattr(pc, "risk", None) or getattr(pc, "risk_hint", None)
            risk = str(r1) if r1 is not None else None

            st1 = getattr(pc, "status", None)
            status = str(st1) if st1 is not None else status

        if not cmd or not str(cmd).strip():
            continue

        out.append(
            ProposedAICommand(
                command_type=str(cmd).strip(),
                payload=args if isinstance(args, dict) else {},
                status=status or "BLOCKED",
                required_approval=requires_approval,
                risk_hint=risk,
            )
        )

    return out


def _merge_agent_trace_into_response(resp: CEOCommandResponse, agent_out: Any) -> None:
    """
    Critical debug hook:
    - Propagates router/agent selection details (selected_agent_id, ranking, etc.)
      from AgentRouterService output trace into the HTTP response trace.
    """
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

    # Merge trace keys (agent/router trace is the useful one)
    if agent_trace:
        resp.trace.update(agent_trace)


# ======================
# ROUTES
# ======================


@router.post("/command/internal")
async def ceo_command(req: CEOCommandRequest = Body(...)) -> CEOCommandResponse:
    _ensure_registry_loaded()

    initiator = (req.initiator or "ceo_dashboard").strip()
    bundle = _build_snapshot_bundle()
    snapshot_meta = {
        "source": "CEOConsoleSnapshotService + KnowledgeSnapshotService(SSOT payload)",
        "ts": _now_iso(),
    }

    # --- READ/WRITE SWITCH (router decides) ---
    mode = decide_read_write(req.text)
    read_only = bool(mode.get("read_only", True))
    require_approval = not read_only
    # -----------------------------------------

    # IMPORTANT:
    # AgentInput.snapshot MUST be the SSOT knowledge payload (goals/tasks/dashboard/...).
    knowledge_payload = bundle.get("knowledge_payload")
    if not isinstance(knowledge_payload, dict):
        knowledge_payload = {}

    agent_input = AgentInput(
        message=req.text,
        snapshot=knowledge_payload,  # SSOT payload to agent
        conversation_id=req.session_id,
        preferred_agent_id=req.preferred_agent_id,
        identity_pack={
            "mode": "ADVISOR" if read_only else "EXECUTOR",
            "read_only": read_only,
            "require_approval": require_approval,
        },
        metadata={
            "initiator": initiator,
            "canon": "ceo_console_router",
            "router_version": ROUTER_VERSION,
            "endpoint": "/internal/ceo-console/command",
            "snapshot_meta": snapshot_meta,
            "read_only": read_only,
            "require_approval": require_approval,
            # UI/dashboard snapshot stays here (not in agent snapshot)
            "ceo_dashboard_snapshot": bundle.get("ceo_dashboard_snapshot") or {},
            "knowledge_snapshot_meta": bundle.get("knowledge_snapshot_meta") or {},
            # optional passthrough
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
        context={
            "canon": "ceo_console_router",
            "initiator": initiator,
            "snapshot": _redact_snapshot_for_response(bundle),
            "snapshot_meta": snapshot_meta,
            "read_only": read_only,
            "require_approval": require_approval,
        },
        trace={
            "router_version": ROUTER_VERSION,
            "decided_mode": mode,
            "initiator": initiator,
            "knowledge_snapshot_meta": bundle.get("knowledge_snapshot_meta") or {},
        },
    )

    # Prefer AgentOutput.text if available; else dict["text"]
    text = (
        getattr(agent_out, "text", None)
        if not isinstance(agent_out, dict)
        else agent_out.get("text")
    )
    if isinstance(text, str):
        resp.summary = text

    resp.proposed_commands = _coerce_proposed_commands(agent_out)

    # NEW: include router selection / ranking / selected_agent_id in response trace
    _merge_agent_trace_into_response(resp, agent_out)

    return resp


@router.post("/command")
async def ceo_command_alias(req: CEOCommandRequest = Body(...)) -> CEOCommandResponse:
    return await ceo_command(req)
