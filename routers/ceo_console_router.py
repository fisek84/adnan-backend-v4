# routers/ceo_console_router.py
from __future__ import annotations

import inspect
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from models.agent_contract import AgentInput, AgentOutput
from services.agent_registry_service import AgentRegistryService
from services.agent_router_service import AgentRouterService

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


class ProposedAICommand(BaseModel):
    command_type: str
    payload: Dict[str, Any] = {}
    status: str = "BLOCKED"
    required_approval: bool = True
    cost_hint: Optional[str] = None
    risk_hint: Optional[str] = None


class CEOCommandResponse(BaseModel):
    ok: bool = True
    read_only: bool = True
    context: Dict[str, Any] = {}
    summary: str = ""
    questions: List[str] = []
    plan: List[str] = []
    options: List[str] = []
    proposed_commands: List[ProposedAICommand] = []
    trace: Dict[str, Any] = {}


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
    # 🔴 SNAPSHOT FROM REQUEST (OVERRIDE)
    # ===============================
    if req.context_hint and isinstance(req.context_hint, dict):
        req_snapshot = req.context_hint.get("snapshot")
        if isinstance(req_snapshot, dict):
            ctx["snapshot"] = _compact_dashboard_snapshot(
                {
                    "source": "request.context_hint",
                    "dashboard": req_snapshot,
                }
            )
            ctx["snapshot_meta"] = {
                "snapshotter": "request",
                "available": True,
                "source": "request.context_hint",
            }
            return ctx  # ⬅️ PREKID: NE ZOVI SNAPSHOT SERVIS

    # ===============================
    # FALLBACK: SERVER SNAPSHOT
    # ===============================
    try:
        from services.ceo_console_snapshot_service import CEOConsoleSnapshotService

        snapshotter = CEOConsoleSnapshotService()
        snap = snapshotter.snapshot()
        snap = await _maybe_await(snap)
        ctx["snapshot"] = _compact_dashboard_snapshot(snap)
        ctx["snapshot_meta"] = {
            "snapshotter": "CEOConsoleSnapshotService",
            "available": True,
            "source": "server",
        }
    except Exception as e:
        ctx["snapshot"] = {"available": False, "error": str(e)}
        ctx["snapshot_meta"] = {
            "snapshotter": "exception",
            "available": False,
            "error": str(e),
        }

    return ctx


# ======================
# AGENT EXECUTION
# ======================


async def _ceo_advice_via_agent_router(
    text: str, context: Dict[str, Any]
) -> Dict[str, Any]:
    _ensure_registry_loaded()

    agent_input = AgentInput(
        message=text,
        snapshot=context.get("snapshot"),
        preferred_agent_id="ceo_advisor",
        metadata={"read_only": True},
    )

    out: AgentOutput = await _agent_router.route(agent_input)

    if not out.text:
        out.text = "Nema dostupnih podataka u snapshotu."

    proposed = [
        ProposedAICommand(
            command_type=p.command,
            payload=p.args or {},
        )
        for p in out.proposed_commands or []
        if p.command
    ]

    if not proposed:
        proposed.append(
            ProposedAICommand(
                command_type="refresh_snapshot",
                payload={"source": "ceo_dashboard"},
            )
        )

    return {
        "summary": out.text,
        "proposed_commands": proposed,
        "trace": out.trace or {},
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
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=400, detail="text required")

    context = await _build_context(req)
    result = await _ceo_advice_via_agent_router(text, context)

    return CEOCommandResponse(
        ok=True,
        read_only=True,
        context=context,
        summary=result.get("summary", ""),
        proposed_commands=result.get("proposed_commands", []),
        trace=result.get("trace", {}),
    )


ceo_console_router = router
