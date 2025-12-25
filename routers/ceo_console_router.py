# routers/ceo_console_router.py
from __future__ import annotations

import inspect
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from services.agent_registry_service import AgentRegistryService
from services.agent_router_service import AgentRouterService

router = APIRouter(prefix="/ceo-console", tags=["CEO Console"])

# ============================================================
# CANON AGENTIC LAYER (READ/PROPOSE ONLY)
# ============================================================

_agent_registry = AgentRegistryService()
_agent_router = AgentRouterService(_agent_registry)


def _ensure_registry_loaded() -> None:
    """
    Primary load should happen in gateway lifespan.
    This is a safe fallback to keep CEO console read-only working.
    """
    try:
        if not _agent_registry.list_agents():
            _agent_registry.load_from_agents_json("config/agents.json", clear=True)
    except Exception:
        # Fail closed: CEO console remains read-only, but may have degraded agent availability.
        pass


# ============================================================
# MODELS (READ-ONLY: CEO Command is advisory only)
# ============================================================


class CEOCommandRequest(BaseModel):
    """
    CEO Command request (READ-only).
    This endpoint MUST NOT perform any WRITE / side effects.
    """

    text: str = Field(..., min_length=1, description="Natural language input from CEO.")
    initiator: Optional[str] = Field(
        default=None,
        description="Who initiated the command (for UX/audit display only).",
    )
    session_id: Optional[str] = Field(
        default=None,
        description="Client session id (for UX correlation only).",
    )
    context_hint: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Optional extra context provided by UI (READ-only).",
    )


class ProposedAICommand(BaseModel):
    command_type: str = Field(..., description="Type/name of the proposed command.")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Command payload.")
    status: str = Field(default="BLOCKED", description="Always BLOCKED at proposal time.")
    required_approval: bool = Field(default=True, description="Always true for side-effects.")
    cost_hint: Optional[str] = Field(default=None, description="Human-readable estimate.")
    risk_hint: Optional[str] = Field(default=None, description="Human-readable risks.")


class CEOCommandResponse(BaseModel):
    ok: bool = True
    read_only: bool = True

    context: Dict[str, Any] = Field(default_factory=dict)

    summary: str = ""
    questions: List[str] = Field(default_factory=list)
    plan: List[str] = Field(default_factory=list)
    options: List[str] = Field(default_factory=list)

    proposed_commands: List[ProposedAICommand] = Field(default_factory=list)

    trace: Dict[str, Any] = Field(default_factory=dict)


# ============================================================
# INTERNAL HELPERS (READ-ONLY ONLY)
# ============================================================


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _safe_import_snapshotter() -> Any:
    """
    Priority order:
      1) services.ceo_console_snapshot_service.CEOConsoleSnapshotService
      2) services.system_read_executor.SystemReadExecutor (legacy)
      3) None (fallback)
    """
    try:
        from services.ceo_console_snapshot_service import (  # type: ignore
            CEOConsoleSnapshotService,
        )

        return CEOConsoleSnapshotService()
    except Exception:
        pass

    try:
        from services.system_read_executor import SystemReadExecutor  # type: ignore

        return SystemReadExecutor()
    except Exception:
        return None


def _try_load_core_snapshot_fallback() -> Dict[str, Any]:
    snap: Dict[str, Any] = {"available": False, "source": "fallback"}

    try:
        from services.adnan_mode_service import load_mode  # type: ignore
        from services.adnan_state_service import load_state  # type: ignore
        from services.identity_loader import load_identity  # type: ignore

        snap["identity"] = load_identity()
        snap["mode"] = load_mode()
        snap["state"] = load_state()
    except Exception as e:
        snap["identity"] = {"available": False, "error": str(e)}
        snap["mode"] = {"available": False, "error": str(e)}
        snap["state"] = {"available": False, "error": str(e)}

    try:
        from services.knowledge_snapshot_service import KnowledgeSnapshotService  # type: ignore

        snap["knowledge_snapshot"] = KnowledgeSnapshotService.get_snapshot()
    except Exception as e:
        snap["knowledge_snapshot"] = {"available": False, "error": str(e)}

    return snap


def _as_list_of_str(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [x for x in value if isinstance(x, str) and x.strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        if "\n" in stripped:
            return [ln.strip() for ln in stripped.splitlines() if ln.strip()]
        return [stripped]
    return []


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

    snapshotter = _safe_import_snapshotter()
    if snapshotter is None:
        fallback = _try_load_core_snapshot_fallback()
        fallback["reason"] = "No snapshotter available; using fallback snapshot (READ-only)."
        ctx["snapshot"] = fallback
        ctx["snapshot_meta"] = {
            "snapshotter": None,
            "available": False,
            "source": "fallback",
        }
        return ctx

    meta = {
        "snapshotter": snapshotter.__class__.__name__,
        "available": None,
        "source": None,
        "error": None,
    }

    try:
        if hasattr(snapshotter, "snapshot"):
            snap = snapshotter.snapshot()  # type: ignore[misc]
        elif hasattr(snapshotter, "build_snapshot"):
            snap = snapshotter.build_snapshot()  # type: ignore[misc]
        elif hasattr(snapshotter, "get_snapshot"):
            snap = snapshotter.get_snapshot()  # type: ignore[misc]
        else:
            snap = {
                "available": False,
                "source": meta["snapshotter"],
                "error": "No snapshot method found.",
            }

        snap = await _maybe_await(snap)

        if isinstance(snap, dict):
            if "available" not in snap:
                snap["available"] = True
            if "source" not in snap:
                snap["source"] = meta["snapshotter"]

            meta["available"] = snap.get("available")
            meta["source"] = snap.get("source")
            meta["error"] = snap.get("error")
            ctx["snapshot"] = snap
        else:
            meta["available"] = True
            meta["source"] = meta["snapshotter"]
            ctx["snapshot"] = {
                "available": True,
                "source": meta["snapshotter"],
                "snapshot": snap,
            }

    except Exception as e:
        meta["available"] = False
        meta["source"] = "exception"
        meta["error"] = str(e)
        ctx["snapshot"] = {"available": False, "source": "exception", "error": str(e)}

    ctx["snapshot_meta"] = meta
    return ctx


def _map_agent_proposals_to_ceo_commands(proposed: List[ProposedCommand]) -> List[ProposedAICommand]:
    out: List[ProposedAICommand] = []
    for pc in proposed or []:
        # ProposedCommand is already proposal-only; enforce BLOCKED and read-only semantics.
        cmd_type = (pc.command or "").strip()
        if not cmd_type:
            continue
        payload = pc.args if isinstance(pc.args, dict) else {}
        out.append(
            ProposedAICommand(
                command_type=cmd_type,
                payload=payload,
                status="BLOCKED",
                required_approval=bool(getattr(pc, "requires_approval", True)),
                cost_hint=None,
                risk_hint=str(getattr(pc, "risk", "") or "").strip() or None,
            )
        )
    return out


async def _ceo_advice_via_agent_router(text: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    READ-ONLY advisory via FAZA 4 agentic layer.
    - No tools
    - No side effects
    - No approvals
    - No execution
    """
    _ensure_registry_loaded()

    snapshot = context.get("snapshot") if isinstance(context.get("snapshot"), dict) else {}
    identity_pack: Dict[str, Any] = {
        "initiator": context.get("initiator"),
        "session_id": context.get("session_id"),
    }
    # Remove None keys
    identity_pack = {k: v for k, v in identity_pack.items() if v is not None}

    agent_input = AgentInput(
        message=text,
        identity_pack=identity_pack,
        snapshot=snapshot,
        preferred_agent_id="ceo_clone",  # deterministic for CEO console
        metadata={
            "endpoint": "/ceo-console/command",
            "read_only": True,
            "canon": "read_propose_only",
            "ui_context_hint": context.get("ui_context_hint"),
        },
    )

    out: AgentOutput = _agent_router.route(agent_input)

    # Defense-in-depth
    out.read_only = True
    for pc in out.proposed_commands or []:
        pc.dry_run = True

    trace = out.trace if isinstance(out.trace, dict) else {}
    trace["read_only_guard"] = True
    trace["canon_read_only_guard"] = True

    snap_meta = context.get("snapshot_meta") if isinstance(context.get("snapshot_meta"), dict) else {}
    if snap_meta:
        trace["snapshot_meta"] = snap_meta

    return {
        "summary": out.text or "",
        "questions": [],
        "plan": [],
        "options": [],
        "proposed_commands": _map_agent_proposals_to_ceo_commands(out.proposed_commands),
        "trace": trace,
    }


# ============================================================
# ROUTES
# ============================================================


@router.get("/status")
def status() -> Dict[str, Any]:
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
        raise HTTPException(status_code=400, detail="text is required")

    context = await _build_context(req)

    # FAZA 4: Use canonical agent router (read/propose only)
    result = await _ceo_advice_via_agent_router(text=text, context=context)

    summary_val = result.get("summary")
    if isinstance(summary_val, str):
        summary = summary_val
    else:
        summary_list = _as_list_of_str(summary_val)
        summary = "\n".join(summary_list) if summary_list else ""

    questions_s = _as_list_of_str(result.get("questions"))
    plan_s = _as_list_of_str(result.get("plan"))
    options_s = _as_list_of_str(result.get("options"))

    trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
    proposed = result.get("proposed_commands") or []
    if not isinstance(proposed, list):
        proposed = []

    return CEOCommandResponse(
        ok=True,
        read_only=True,
        context=context,
        summary=summary,
        questions=questions_s,
        plan=plan_s,
        options=options_s,
        proposed_commands=[p for p in proposed if isinstance(p, ProposedAICommand)],
        trace=trace,
    )


ceo_console_router = router
