# routers/ceo_console_router.py
from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field, model_validator

from models.agent_contract import AgentInput
from services.agent_registry_service import AgentRegistryService
from services.agent_router_service import AgentRouterService
from services.ceo_console_snapshot_service import CEOConsoleSnapshotService
from services.knowledge_snapshot_service import KnowledgeSnapshotService
from services.intent_mode_service import decide_read_write  # ✅ KLJUČNO

ROUTER_VERSION = "2025-12-30-read-write-switch-v1"

router = APIRouter(prefix="/internal/ceo-console", tags=["CEO Console"])

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

    @model_validator(mode="before")
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


def _build_snapshot() -> Dict[str, Any]:
    try:
        ceo_dash = CEOConsoleSnapshotService().snapshot() or {}
    except Exception:
        ceo_dash = {}

    try:
        ks = KnowledgeSnapshotService.get_snapshot() or {}
    except Exception:
        ks = {}

    return {
        "ceo_dashboard_snapshot": ceo_dash,
        "knowledge_snapshot_meta": {
            "ready": ks.get("ready"),
            "last_sync": ks.get("last_sync"),
        },
    }


def _coerce_proposed_commands(agent_output: Any) -> List[ProposedAICommand]:
    out: List[ProposedAICommand] = []

    pcs = None
    if isinstance(agent_output, dict):
        pcs = agent_output.get("proposed_commands")
    else:
        pcs = getattr(agent_output, "proposed_commands", None)

    if not isinstance(pcs, list):
        return out

    for pc in pcs:
        if isinstance(pc, dict):
            cmd = pc.get("command") or pc.get("command_type")
            if not cmd:
                continue
            out.append(
                ProposedAICommand(
                    command_type=cmd,
                    payload=pc.get("args") or pc.get("payload") or {},
                    status=pc.get("status", "BLOCKED"),
                    required_approval=bool(pc.get("requires_approval", True)),
                    risk_hint=pc.get("risk") or pc.get("risk_hint"),
                )
            )

    return out


# ======================
# ROUTES
# ======================


@router.post("/command/internal")
async def ceo_command(req: CEOCommandRequest = Body(...)) -> CEOCommandResponse:
    _ensure_registry_loaded()

    initiator = (req.initiator or "ceo_dashboard").strip()
    snapshot = _build_snapshot()
    snapshot_meta = {"source": "CEOConsoleSnapshotService", "ts": _now_iso()}

    # =====================================================
    # 🔥 OVO JE SWITCH KOJI SI TRAŽIO
    # =====================================================
    mode = decide_read_write(req.text)

    read_only = bool(mode.get("read_only", True))
    require_approval = not read_only

    # =====================================================

    agent_input = AgentInput(
        message=req.text,
        snapshot=snapshot,
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
            "snapshot_meta": snapshot_meta,
            "read_only": read_only,
            "require_approval": require_approval,
        },
    )

    try:
        agent_out = await _maybe_await(_agent_router.route(agent_input))
    except Exception as e:
        agent_out = {"text": f"Agent error: {e}"}

    resp = CEOCommandResponse(
        ok=True,
        read_only=read_only,
        context={
            "canon": "ceo_console_router",
            "initiator": initiator,
            "snapshot": snapshot,
            "snapshot_meta": snapshot_meta,
            "read_only": read_only,
            "require_approval": require_approval,
        },
        trace={
            "router_version": ROUTER_VERSION,
            "decided_mode": mode,
            "initiator": initiator,
        },
    )

    text = (
        getattr(agent_out, "text", None)
        if not isinstance(agent_out, dict)
        else agent_out.get("text")
    )
    if isinstance(text, str):
        resp.summary = text

    resp.proposed_commands = _coerce_proposed_commands(agent_out)

    return resp


@router.post("/command")
async def ceo_command_alias(req: CEOCommandRequest = Body(...)) -> CEOCommandResponse:
    return await ceo_command(req)
