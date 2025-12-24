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
    payload: Dict[str, Any] = Field(
        default_factory=dict, description="Command payload."
    )
    status: str = Field(
        default="BLOCKED", description="Always BLOCKED at proposal time."
    )
    required_approval: bool = Field(
        default=True, description="Always true for side-effects."
    )
    cost_hint: Optional[str] = Field(
        default=None, description="Human-readable estimate."
    )
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
        from services.knowledge_snapshot_service import (  # type: ignore
            KnowledgeSnapshotService,
        )

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
        fallback["reason"] = (
            "No snapshotter available; using fallback snapshot (READ-only)."
        )
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
            # Ensure canonical fields are visible to UX
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


async def _llm_advice(text: str, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    READ-ONLY advisory:
    - No tools / no side effects.
    - Uses OpenAIAssistantExecutor.ceo_command if available.
    """
    try:
        from services.agent_router.openai_assistant_executor import (  # type: ignore
            OpenAIAssistantExecutor,
        )

        execr = OpenAIAssistantExecutor()

        safe_context = dict(context)
        canon = dict(safe_context.get("canon") or {})
        canon["read_only"] = True
        canon["no_tools"] = True
        canon["no_side_effects"] = True
        safe_context["canon"] = canon

        if not hasattr(execr, "ceo_command"):
            raise RuntimeError("OpenAIAssistantExecutor.ceo_command is not available")

        result = await execr.ceo_command(text=text, context=safe_context)  # type: ignore[misc]

        if not isinstance(result, dict) or not result:
            raise RuntimeError("CEO advisory returned empty/invalid payload")

        # Hard guard: forbid tool/action fields
        if any(
            k in result
            for k in (
                "tool_calls",
                "required_action",
                "tool_outputs",
                "actions",
                "executed_commands",
            )
        ):
            raise RuntimeError(
                "READ-ONLY violation: tool/action fields present in result"
            )

        trace = result.get("trace") if isinstance(result.get("trace"), dict) else {}
        trace["read_only_guard"] = True
        trace["canon_read_only_guard"] = True

        # Carry snapshot meta into trace so UX always sees provenance
        snap_meta = (
            context.get("snapshot_meta")
            if isinstance(context.get("snapshot_meta"), dict)
            else {}
        )
        if snap_meta:
            trace["snapshot_meta"] = snap_meta

        result["trace"] = trace
        return result

    except Exception as e:
        return {
            "summary": (
                "CEO zahtjev je primljen. Sistem radi u READ-only modu i priprema okvir "
                "za planiranje na osnovu dostupnog snapshot konteksta. Za punu dubinu, "
                "LLM executor mora biti aktivan i povezan."
            ),
            "questions": [
                "Koji je tačan cilj i rok (datum) i šta je definicija uspjeha (prihod/profit)?",
                "Koji kanal je prioritet (postojeći klijenti, outreach, partneri) i koji je budžet/limit?",
            ],
            "plan": [
                "Validirati cilj/rok i postojeće konverzije (ponuda, cijena, kanal).",
                "Izvući relevantno iz SOP/Plans/Time management izvora (READ).",
                "Razbiti cilj na dnevne targete i taskove (prodaja/operacije/marketing).",
                "Predložiti 2–3 opcije i jasno označiti rizike/pretpostavke.",
            ],
            "options": [
                "Opcija A: Fokus na postojeće klijente (brže, niži rizik).",
                "Opcija B: Brzi outreach sa jednostavnom ponudom (više volumena, veći rizik).",
                "Opcija C: Partner kanal (sporiji start, potencijalno skalabilno).",
            ],
            "proposed_commands": [],
            "trace": {"llm": "fallback", "error": str(e), "read_only_guard": True},
        }


def _normalize_proposed_commands(raw: Any) -> List[ProposedAICommand]:
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
    result = await _llm_advice(text=text, context=context)

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
