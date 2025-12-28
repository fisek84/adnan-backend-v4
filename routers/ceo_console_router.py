# routers/ceo_console_router.py
import os

from __future__ import annotations

import inspect
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from models.agent_contract import AgentInput, AgentOutput
from services.agent_registry_service import get_agent_registry_service
from services.agent_router_service import AgentRouterService
from system_version import SYSTEM_NAME, VERSION

router = APIRouter(prefix="/ceo-console", tags=["CEO Console"])

# IMPORTANT:
# - Do NOT create a new AgentRegistryService() here.
# - Use SSOT singleton (same instance as gateway_server.py uses).
_agent_registry = get_agent_registry_service()
_agent_router = AgentRouterService(_agent_registry)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _agents_json_path() -> str:
    # mirror gateway_server.py behavior
    p = (os.getenv("AGENTS_JSON_PATH") or "").strip()
    if p:
        return p
    p2 = (os.getenv("AGENTS_REGISTRY_PATH") or "").strip()
    if p2:
        return p2
    return str(_repo_root() / "config" / "agents.json")


def _ensure_registry_loaded() -> None:
    """
    Ensure agents.json is loaded into the singleton registry.
    Safe to call multiple times.
    """
    try:
        if not _agent_registry.list_agents():
            _agent_registry.load_from_agents_json(_agents_json_path(), clear=True)
    except Exception:
        # do not crash API on load issues; agent router will handle
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
    payload: Dict[str, Any] = Field(default_factory=dict)
    status: str = "BLOCKED"
    required_approval: bool = True
    cost_hint: Optional[str] = None
    risk_hint: Optional[str] = None


class CEOCommandResponse(BaseModel):
    ok: bool = True
    read_only: bool = True
    context: Dict[str, Any] = Field(default_factory=dict)

    # IMPORTANT: frontend very often expects "text"
    # We keep "summary" too for backward compatibility.
    text: str = ""
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
            "goals": [_compact_item(g) for g in (dashboard.get("goals", []) or [])],
            "tasks": [_compact_item(t) for t in (dashboard.get("tasks", []) or [])],
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
            return ctx  # do not call server snapshotter

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
# DETERMINISTIC FALLBACKS (NO GUESSING)
# ======================


_IDENTITY_RE = re.compile(
    r"^\s*(ko\s*si\s*ti|ko\s*si|šta\s*si|sta\s*si|who\s*are\s*you)\s*\??\s*$",
    re.IGNORECASE,
)


def _identity_answer() -> str:
    return (
        f"Ja sam {SYSTEM_NAME} CEO Advisor (read-only) servis. "
        f"Verzija: {VERSION}. "
        "Mogu: (1) dati sažetak dashboard snapshot-a, (2) predložiti komande kao PROPOSALS "
        "koje idu kroz approval flow, i (3) objasniti status sistema. "
        "Ako želiš akciju, napiši konkretno: npr. 'kreiraj cilj X', 'prikaži top 5 taskova', "
        "'predloži plan za KPI OS'."
    )


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
        metadata={
            "read_only": True,
            # give the agent a chance to answer the question,
            # but keep system safe:
            "mode": "ceo_console_read_only",
        },
    )

    out: AgentOutput = await _agent_router.route(agent_input)

    summary = (out.text or "").strip()
    if not summary:
        summary = "Nema dostupnih podataka u snapshotu."

    proposed = [
        ProposedAICommand(
            command_type=p.command,
            payload=p.args or {},
        )
        for p in (out.proposed_commands or [])
        if getattr(p, "command", None)
    ]

    # Always ensure at least 1 proposed command exists (your requirement)
    if not proposed:
        proposed.append(
            ProposedAICommand(
                command_type="refresh_snapshot",
                payload={"source": "ceo_dashboard"},
            )
        )

    return {
        "summary": summary,
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
    text_in = (req.text or "").strip()
    if not text_in:
        raise HTTPException(status_code=400, detail="text required")

    context = await _build_context(req)

    # Deterministic identity answer (no dependence on LLM prompt)
    if _IDENTITY_RE.match(text_in):
        summary = _identity_answer()
        proposed = [
            ProposedAICommand(
                command_type="refresh_snapshot",
                payload={"source": "ceo_console"},
            )
        ]
        return CEOCommandResponse(
            ok=True,
            read_only=True,
            context=context,
            text=summary,
            summary=summary,
            proposed_commands=proposed,
            trace={"path": "deterministic_identity"},
        )

    # Normal path: agent router
    result = await _ceo_advice_via_agent_router(text_in, context)
    summary = (result.get("summary") or "").strip()

    return CEOCommandResponse(
        ok=True,
        read_only=True,
        context=context,
        text=summary,  # IMPORTANT for frontend
        summary=summary,
        proposed_commands=result.get("proposed_commands", []),
        trace=result.get("trace", {}),
    )


ceo_console_router = router
