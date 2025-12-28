# routers/ceo_console_router.py
from __future__ import annotations

import inspect
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from models.agent_contract import AgentInput, AgentOutput

# IMPORTANT: koristi SSOT singleton registry (isti kao gateway_server.py)
from services.agent_registry_service import get_agent_registry_service
from services.agent_router_service import AgentRouterService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ceo-console", tags=["CEO Console"])

# SSOT (singleton) registry + router
_agent_registry = get_agent_registry_service()
_agent_router = AgentRouterService(_agent_registry)


def _resolve_agents_json_path() -> str:
    """
    Repo-root aware path. U runtime-u na Renderu /app je root projekta.
    Koristi isti default koji gateway_server.py koristi (/app/config/agents.json).
    """
    # Ako ima env override, poštuj ga (kanonski)
    p = (inspect_os_getenv("AGENTS_JSON_PATH") or "").strip()
    if p:
        return p
    p2 = (inspect_os_getenv("AGENTS_REGISTRY_PATH") or "").strip()
    if p2:
        return p2
    return "config/agents.json"


def inspect_os_getenv(name: str) -> Optional[str]:
    # lokalni helper da izbjegnemo circular import s gateway_server
    try:
        import os

        return os.getenv(name)
    except Exception:
        return None


def _ensure_registry_loaded() -> None:
    """
    Osiguraj da su agenti učitani. Ne pravimo nove instance registra.
    """
    try:
        agents = _agent_registry.list_agents()
        if agents:
            return
        path = _resolve_agents_json_path()
        _agent_registry.load_from_agents_json(path, clear=True)
        logger.info("CEO console loaded agent registry: %s", path)
    except Exception as exc:  # noqa: BLE001
        # Ne ruši API; ali ostavi trag u logu
        logger.warning("CEO console registry load failed: %s", exc)


# ======================
# MODELS
# ======================


class CEOCommandRequest(BaseModel):
    text: str = Field(..., min_length=1)
    initiator: Optional[str] = None
    session_id: Optional[str] = None
    context_hint: Optional[Dict[str, Any]] = None


class ProposedAICommand(BaseModel):
    command_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    status: str = "BLOCKED"
    required_approval: bool = True
    cost_hint: Optional[str] = None
    risk_hint: Optional[str] = None


class CEOCommandResponse(BaseModel):
    ok: bool = True
    read_only: bool = True
    context: Dict[str, Any] = Field(default_factory=dict)

    # UI polja
    summary: str = ""
    text: str = ""  # IMPORTANT: frontend očekuje `text` u praksi
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


_HEAVY_KEYS = {"properties", "properties_text", "properties_types", "raw"}


def _compact_item(item: Dict[str, Any]) -> Dict[str, Any]:
    keep = {
        "id",
        "title",
        "name",
        "status",
        "priority",
        "due_date",
        "lead",
        "project",
        "goal",
    }
    return {k: item.get(k) for k in keep if k in item}


def _compact_dashboard_snapshot(snap: Dict[str, Any]) -> Dict[str, Any]:
    dashboard = snap.get("dashboard", {})
    return {
        "available": True,
        "source": snap.get("source"),
        "kind": "dashboard_snapshot",
        "dashboard": {
            "goals": [_compact_item(g) for g in dashboard.get("goals", [])],
            "tasks": [_compact_item(t) for t in dashboard.get("tasks", [])],
        },
    }


# ======================
# CONTEXT
# ======================


async def _build_context(req: CEOCommandRequest) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "canon": {
            "read_only": True,
            "chat_is_read_only": True,
            "write_requires_approval": True,
            "no_side_effects": True,
            "no_tools": True,
        }
    }

    if req.initiator:
        ctx["initiator"] = req.initiator
    if req.session_id:
        ctx["session_id"] = req.session_id
    if req.context_hint:
        ctx["ui_context_hint"] = req.context_hint

    # ===============================
    # SNAPSHOT FROM REQUEST (OVERRIDE)
    # ===============================
    if req.context_hint and isinstance(req.context_hint, dict):
        req_snapshot = req.context_hint.get("snapshot")
        if isinstance(req_snapshot, dict):
            ctx["snapshot"] = _compact_dashboard_snapshot(
                {"source": "request.context_hint", "dashboard": req_snapshot}
            )
            ctx["snapshot_meta"] = {
                "snapshotter": "request",
                "available": True,
                "source": "request.context_hint",
            }
            return ctx  # ne zovi server snapshot

    # ===============================
    # FALLBACK: SERVER SNAPSHOT
    # ===============================
    try:
        from services.ceo_console_snapshot_service import CEOConsoleSnapshotService

        snapshotter = CEOConsoleSnapshotService()
        snap = snapshotter.snapshot()
        snap = await _maybe_await(snap)
        if not isinstance(snap, dict):
            raise RuntimeError("snapshot_invalid_type")

        ctx["snapshot"] = _compact_dashboard_snapshot(snap)
        ctx["snapshot_meta"] = {
            "snapshotter": "CEOConsoleSnapshotService",
            "available": True,
            "source": "server",
        }
    except Exception as exc:  # noqa: BLE001
        ctx["snapshot"] = {"available": False, "error": str(exc)}
        ctx["snapshot_meta"] = {
            "snapshotter": "exception",
            "available": False,
            "error": str(exc),
        }

    return ctx


# ======================
# AGENT EXECUTION
# ======================


async def _ceo_advice_via_agent_router(
    text: str, context: Dict[str, Any], *, session_id: Optional[str]
) -> Dict[str, Any]:
    _ensure_registry_loaded()

    preferred = "ceo_advisor"
    # dozvoli UI override agenta
    ui_hint = context.get("ui_context_hint")
    if isinstance(ui_hint, dict):
        pa = ui_hint.get("preferred_agent_id")
        if isinstance(pa, str) and pa.strip():
            preferred = pa.strip()

    agent_input = AgentInput(
        message=text,
        snapshot=context.get("snapshot"),
        preferred_agent_id=preferred,
        metadata={
            "read_only": True,
            "session_id": session_id,
            "initiator": context.get("initiator"),
            "canon": context.get("canon"),
        },
    )

    out: AgentOutput = await _agent_router.route(agent_input)

    # hard guarantee da UI ne ostane bez teksta
    if not getattr(out, "text", None):
        out.text = "Nema odgovora od agenta (prazan output)."

    proposed: List[ProposedAICommand] = []
    try:
        for p in out.proposed_commands or []:
            if not getattr(p, "command", None):
                continue
            proposed.append(
                ProposedAICommand(
                    command_type=p.command,
                    payload=p.args or {},
                )
            )
    except Exception as exc:  # noqa: BLE001
        # ne ruši, samo zabilježi
        tr = out.trace or {}
        tr["proposed_parse_error"] = str(exc)
        out.trace = tr

    if not proposed:
        proposed.append(
            ProposedAICommand(
                command_type="refresh_snapshot",
                payload={"source": "ceo_dashboard"},
            )
        )

    return {
        "summary": out.text,
        "text": out.text,
        "proposed_commands": proposed,
        "trace": out.trace or {},
        "agent_id": getattr(out, "agent_id", None),
    }


# ======================
# ROUTES
# ======================


@router.get("/status")
def ceo_console_status() -> Dict[str, Any]:
    return {
        "ok": True,
        "read_only": True,
        "ceo_console": "online",
        "canon": {
            "chat_is_read_only": True,
            "write_requires_approval": True,
            "commands_are_proposals": True,
            "no_side_effects": True,
            "no_tools": True,
        },
    }


@router.post("/command", response_model=CEOCommandResponse)
async def ceo_command(req: CEOCommandRequest = Body(...)) -> CEOCommandResponse:
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")

    context = await _build_context(req)
    result = await _ceo_advice_via_agent_router(
        text, context, session_id=req.session_id
    )

    summary = str(result.get("summary") or "")
    out_text = str(result.get("text") or summary)

    trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
    trace["preferred_agent_id"] = (context.get("ui_context_hint", {}) or {}).get(
        "preferred_agent_id"
    ) or "ceo_advisor"
    trace["agent_id"] = result.get("agent_id")

    return CEOCommandResponse(
        ok=True,
        read_only=True,
        context=context,
        summary=summary,
        text=out_text,
        proposed_commands=result.get("proposed_commands", []),
        trace=trace,
    )


ceo_console_router = router
