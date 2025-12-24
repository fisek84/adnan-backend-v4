# routers/ceo_console_router.py
from __future__ import annotations

import inspect
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/ceo-console", tags=["CEO Console"])


# ============================================================
# MODELS (READ-ONLY: CEO Command is advisory only)
# ============================================================


class CEOCommandRequest(BaseModel):
    """
    CEO Command request (READ-only).
    This endpoint MUST NOT perform any WRITE / side effects.
    It may only:
      - read system context (identity/memory/SOP/state)
      - propose AICommands (BLOCKED)
      - ask clarification questions if intent is unclear
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
    """
    A proposed command that is NOT executed here.
    Status is always BLOCKED; execution requires explicit approval elsewhere.
    """

    command_type: str = Field(..., description="Type/name of the proposed command.")
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description="Command payload.",
    )
    status: str = Field(
        default="BLOCKED",
        description="Always BLOCKED at proposal time.",
    )
    required_approval: bool = Field(
        default=True,
        description="Always true for any command with side-effects.",
    )
    cost_hint: Optional[str] = Field(
        default=None,
        description="Human-readable estimate (time/resources/authority).",
    )
    risk_hint: Optional[str] = Field(
        default=None,
        description="Human-readable risks/side effects if executed.",
    )


class CEOCommandResponse(BaseModel):
    ok: bool = True
    read_only: bool = True

    # What the system used (READ)
    context: Dict[str, Any] = Field(default_factory=dict)

    # What the system says (ADVICE)
    summary: str = ""
    questions: List[str] = Field(default_factory=list)
    plan: List[str] = Field(default_factory=list)
    options: List[str] = Field(default_factory=list)

    # What the system proposes (BLOCKED commands; no execution)
    proposed_commands: List[ProposedAICommand] = Field(default_factory=list)

    # Debug/trace (safe to show)
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
    Returns an object that can build a READ-only context snapshot.
    This is intentionally dynamic to avoid hard crashes if internals move.
    """
    try:
        from services.system_read_executor import SystemReadExecutor  # type: ignore

        return SystemReadExecutor()
    except Exception:
        return None


def _try_load_core_snapshot_fallback() -> Dict[str, Any]:
    """
    Best-effort READ-only fallback snapshot if SystemReadExecutor doesn't exist.
    Must not write or persist anything.
    """
    snap: Dict[str, Any] = {"available": True, "source": "fallback"}

    # Identity / mode / state (pure reads)
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

    # Knowledge snapshot (cached READ)
    try:
        from services.knowledge_snapshot_service import (  # type: ignore
            KnowledgeSnapshotService,
        )

        snap["knowledge_snapshot"] = KnowledgeSnapshotService.get_snapshot()
    except Exception as e:
        snap["knowledge_snapshot"] = {"available": False, "error": str(e)}

    return snap


async def _build_context(req: CEOCommandRequest) -> Dict[str, Any]:
    """
    Build context snapshot (READ-only).
    Must not persist anything.
    """
    ctx: Dict[str, Any] = {
        "canon": {
            "read_only": True,
            "chat_is_read_only": True,
            "write_requires_approval": True,
            "no_side_effects": True,
        }
    }

    # Lightweight request metadata (safe)
    if req.initiator:
        ctx["initiator"] = req.initiator
    if req.session_id:
        ctx["session_id"] = req.session_id
    if req.context_hint:
        ctx["ui_context_hint"] = req.context_hint

    snapshotter = _safe_import_snapshotter()
    if snapshotter is None:
        fallback = _try_load_core_snapshot_fallback()
        fallback["available"] = False
        fallback["reason"] = (
            "SystemReadExecutor not available; using best-effort fallback snapshot."
        )
        ctx["snapshot"] = fallback
        return ctx

    # Try common snapshot APIs without assuming exact signature
    try:
        if hasattr(snapshotter, "snapshot"):
            snap = snapshotter.snapshot()  # type: ignore[misc]
        elif hasattr(snapshotter, "build_snapshot"):
            snap = snapshotter.build_snapshot()  # type: ignore[misc]
        elif hasattr(snapshotter, "get_snapshot"):
            snap = snapshotter.get_snapshot()  # type: ignore[misc]
        else:
            snap = {"available": False, "reason": "No snapshot method found."}

        snap = await _maybe_await(snap)
        ctx["snapshot"] = snap if isinstance(snap, dict) else {"snapshot": snap}
    except Exception as e:
        ctx["snapshot"] = {"available": False, "error": str(e)}

    return ctx


async def _llm_advice(text: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Produce advisory output + proposed commands.

    CANON:
    - READ-ONLY: MUST NOT execute writes / tools / side effects.
    - Uses services-layer SSOT executor (if available): ceo_command(...)
    - If executor is unavailable or errors, returns deterministic fallback.
    """
    try:
        from services.agent_router.openai_assistant_executor import (  # type: ignore
            OpenAIAssistantExecutor,
        )

        execr = OpenAIAssistantExecutor()

        # Force READ-only guard in context, even if caller forgot
        safe_context = dict(context)
        canon = dict(safe_context.get("canon") or {})
        canon["read_only"] = True
        canon["no_tools"] = True
        canon["no_side_effects"] = True
        safe_context["canon"] = canon

        if not hasattr(execr, "ceo_command"):
            raise RuntimeError("OpenAIAssistantExecutor.ceo_command is not available")

        result = await execr.ceo_command(text=text, context=safe_context)  # type: ignore[misc]

        if isinstance(result, dict) and result:
            trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
            trace["canon_read_only_guard"] = True
            result["trace"] = trace
            return result

    except Exception:
        pass

    return {
        "summary": (
            "Primio sam CEO zahtjev i pripremio okvir za planiranje na osnovu dostupnog "
            "READ konteksta. Za punu dubinu, LLM executor treba biti aktivan i povezan na "
            "snapshot (identity/memory/SOP/state)."
        ),
        "questions": [
            "Koji je tačan rok (do kojeg dana u sedmici) i da li 1k BAM znači prihod ili profit?",
            "Koji je trenutno najbliži izvor prihoda (usluga/proizvod) koji možemo skalirati ove sedmice?",
        ],
        "plan": [
            "Definiši cilj (prihod vs profit), rok i minimalne ulaze (ponuda, cijena, kanal).",
            "Izvuci iz SOP/memorije: šta je ranije radilo, koje su aktivne prilike i ograničenja.",
            "Razbij cilj na dnevne targete i konkretne taskove (prodaja, isporuka, marketing).",
            "Predloži 2–3 opcije (konzervativno / agresivno) i odaberi jednu za potencijalno izvršenje.",
        ],
        "options": [
            "Opcija A: Fokus na postojeće klijente (brža prodaja, manji trošak).",
            "Opcija B: Brzi outreach + jednostavna ponuda (više volumena, veći rizik).",
            "Opcija C: Partnerstvo/affiliate (sporije startuje, ali može skalirati).",
        ],
        "proposed_commands": [],
        "trace": {"llm": "fallback"},
    }


def _normalize_proposed_commands(raw: Any) -> List[ProposedAICommand]:
    """
    Normalize proposed commands to strict BLOCKED proposals.
    """
    cmds: List[ProposedAICommand] = []

    if not raw:
        return cmds

    if isinstance(raw, list):
        items = raw
    elif isinstance(raw, dict) and isinstance(raw.get("proposed_commands"), list):
        items = raw["proposed_commands"]
    else:
        return cmds

    for it in items:
        if not isinstance(it, dict):
            continue

        cmd_type = it.get("command_type") or it.get("type") or it.get("name")
        if not isinstance(cmd_type, str) or not cmd_type.strip():
            continue

        payload = it.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        cmds.append(
            ProposedAICommand(
                command_type=cmd_type.strip(),
                payload=payload,
                status="BLOCKED",
                required_approval=True,
                cost_hint=(
                    it.get("cost_hint")
                    if isinstance(it.get("cost_hint"), str)
                    else None
                ),
                risk_hint=(
                    it.get("risk_hint")
                    if isinstance(it.get("risk_hint"), str)
                    else None
                ),
            )
        )

    return cmds


# ============================================================
# ROUTES
# ============================================================


@router.get("/status")
def status() -> Dict[str, Any]:
    """
    READ-only status endpoint for the CEO Console.
    """
    return {
        "ok": True,
        "read_only": True,
        "ceo_console": "online",
        "canon": {
            "chat_is_read_only": True,
            "write_requires_approval": True,
            "commands_are_proposals": True,
        },
    }


@router.post("/command", response_model=CEOCommandResponse)
async def ceo_command(req: CEOCommandRequest = Body(...)) -> CEOCommandResponse:
    """
    CEO Command (READ-only):
    - Builds READ snapshot context (identity/memory/SOP/state)
    - Produces advice + proposed BLOCKED AICommands
    - NEVER executes, NEVER writes, NEVER performs side effects
    """
    text = (req.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="text is required")

    context = await _build_context(req)
    result = await _llm_advice(text=text, context=context)

    summary = result.get("summary") if isinstance(result.get("summary"), str) else ""
    questions = (
        result.get("questions") if isinstance(result.get("questions"), list) else []
    )
    plan = result.get("plan") if isinstance(result.get("plan"), list) else []
    options = result.get("options") if isinstance(result.get("options"), list) else []
    trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}

    questions_s = [q for q in questions if isinstance(q, str)]
    plan_s = [p for p in plan if isinstance(p, str)]
    options_s = [o for o in options if isinstance(o, str)]

    proposed = _normalize_proposed_commands(result)

    return CEOCommandResponse(
        ok=True,
        read_only=True,
        context=context,
        summary=summary,
        questions=questions_s,
        plan=plan_s,
        options=options_s,
        proposed_commands=proposed,
        trace=trace,
    )


ceo_console_router = router
