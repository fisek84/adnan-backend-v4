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

router = APIRouter(prefix="/internal/ceo-console", tags=["CEO Console"])

_agent_registry = AgentRegistryService()
_agent_router = AgentRouterService(_agent_registry)


def _ensure_registry_loaded() -> None:
    try:
        if not _agent_registry.list_agents():
            _agent_registry.load_from_agents_json("config/agents.json", clear=True)
    except Exception:
        # best-effort; router će i dalje pokušati route
        pass


# ======================
# MODELS
# ======================


class CEOCommandRequest(BaseModel):
    """
    Kompatibilnost:
    - frontend/legacy često šalje: prompt / input_text / message / text
    - ponekad je payload ugniježđen u {"data": {...}}
    Ovaj model mapira sve na canonical "text".

    Režimi:
    - read_only: default False (executor mode)
    - require_approval: default True (UI mora tražiti approve prije write)
    - preferred_agent_id: optional override (ako želiš ručno testirati)
    """

    text: str = Field(..., min_length=1)
    initiator: Optional[str] = None
    session_id: Optional[str] = None
    context_hint: Optional[Dict[str, Any]] = None

    read_only: bool = False
    require_approval: bool = True
    preferred_agent_id: Optional[str] = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_legacy_payload(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        # already ok
        t = values.get("text")
        if isinstance(t, str) and t.strip():
            values["text"] = t.strip()
            return values

        # legacy keys on top-level
        for k in ("prompt", "input_text", "message"):
            v = values.get(k)
            if isinstance(v, str) and v.strip():
                values["text"] = v.strip()
                return values

        # nested legacy keys: data.*
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
    read_only: bool = False  # executor-friendly default
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


def _safe_dict(obj: Any) -> Dict[str, Any]:
    if isinstance(obj, dict):
        return obj
    return {}


def _list_agent_ids() -> List[str]:
    """
    Robustno: agent registry može vraćati list[str] ili list[dict]/objekata.
    """
    ids: List[str] = []
    try:
        agents = _agent_registry.list_agents() or []
    except Exception:
        agents = []

    for a in agents:
        if isinstance(a, str) and a:
            ids.append(a)
            continue
        if isinstance(a, dict):
            v = a.get("id") or a.get("agent_id") or a.get("name")
            if isinstance(v, str) and v:
                ids.append(v)
                continue
        v = (
            getattr(a, "id", None)
            or getattr(a, "agent_id", None)
            or getattr(a, "name", None)
        )
        if isinstance(v, str) and v:
            ids.append(v)

    return sorted(set(ids))


def _pick_preferred_agent_id(req: CEOCommandRequest) -> str:
    """
    Bez pogađanja: bira prvi agent iz liste kandidata koji stvarno postoji u registry-u.
    - read_only=True -> prefer ceo_advisor (ako postoji)
    - read_only=False -> prefer executor/ops agent (ako postoji)
    """
    ids = set(_list_agent_ids())

    # ručni override za test
    if isinstance(req.preferred_agent_id, str) and req.preferred_agent_id.strip():
        pid = req.preferred_agent_id.strip()
        return (
            pid if pid in ids else pid
        )  # i ako nije u ids, ostavimo da se vidi u trace-u

    if req.read_only:
        for cand in ("ceo_advisor", "ceo"):
            if cand in ids:
                return cand
        return "ceo_advisor"

    # executor mode
    for cand in ("ceo_executor", "ceo_ops", "notion_ops", "ops", "ceo_advisor"):
        if cand in ids:
            return cand
    return "ceo_executor"


def _build_snapshot() -> Dict[str, Any]:
    """
    SSOT snapshot koji agent koristi.
    """

    def _project_goal(g: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": g.get("id"),
            "name": g.get("name") or g.get("title"),
            "status": g.get("status"),
            "priority": g.get("priority"),
            "deadline": g.get("deadline"),
        }

    def _project_task(t: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": t.get("id"),
            "title": t.get("title") or t.get("name"),
            "status": t.get("status"),
            "priority": t.get("priority"),
            "due_date": t.get("due_date"),
            "lead": t.get("lead"),
        }

    ceo_dash: Dict[str, Any] = {}
    try:
        ceo_dash = CEOConsoleSnapshotService().snapshot() or {}
    except Exception:
        ceo_dash = {}

    dashboard = ceo_dash.get("dashboard")
    if isinstance(dashboard, dict):
        meta = (
            dashboard.get("metadata")
            if isinstance(dashboard.get("metadata"), dict)
            else {}
        )
        include_properties = bool(meta.get("include_properties"))
        include_properties_text = bool(meta.get("include_properties_text"))
        include_raw_pages = bool(meta.get("include_raw_pages"))

        is_compact = (
            (not include_properties)
            and (not include_properties_text)
            and (not include_raw_pages)
        )
        if is_compact:
            goals = dashboard.get("goals")
            tasks = dashboard.get("tasks")

            if isinstance(goals, list):
                dashboard["goals"] = [
                    _project_goal(g) for g in goals if isinstance(g, dict)
                ]
            if isinstance(tasks, list):
                dashboard["tasks"] = [
                    _project_task(t) for t in tasks if isinstance(t, dict)
                ]
            ceo_dash["dashboard"] = dashboard

    ks: Dict[str, Any] = {}
    try:
        ks = KnowledgeSnapshotService.get_snapshot() or {}
    except Exception:
        ks = {}

    return {
        "ceo_dashboard_snapshot": _safe_dict(ceo_dash),
        "knowledge_snapshot_meta": {
            "ready": ks.get("ready"),
            "last_sync": ks.get("last_sync"),
        },
    }


def _extract_dashboard_lists(
    snapshot: Dict[str, Any],
) -> Dict[str, List[Dict[str, Any]]]:
    out = {"goals": [], "tasks": []}

    ceo_dash = snapshot.get("ceo_dashboard_snapshot")
    if not isinstance(ceo_dash, dict):
        return out

    dashboard = ceo_dash.get("dashboard")
    if not isinstance(dashboard, dict):
        return out

    goals = dashboard.get("goals")
    tasks = dashboard.get("tasks")

    if isinstance(goals, list):
        out["goals"] = [g for g in goals if isinstance(g, dict)]
    if isinstance(tasks, list):
        out["tasks"] = [t for t in tasks if isinstance(t, dict)]

    return out


def _format_summary_from_snapshot(snapshot: Dict[str, Any]) -> str:
    lists = _extract_dashboard_lists(snapshot)
    goals = lists["goals"]
    tasks = lists["tasks"]

    lines: List[str] = []
    lines.append("GOALS (top 3)")

    if not goals:
        lines.append("NEMA DOVOLJNO PODATAKA U SNAPSHOT-U")
    else:
        for g in goals[:3]:
            name = g.get("name") or g.get("title") or "NEMA PODATAKA"
            status = g.get("status") or "NEMA PODATAKA"
            priority = g.get("priority") or "NEMA PODATAKA"
            lines.append(f"{name} | {status} | {priority}")

    lines.append("")
    lines.append("TASKS (top 5)")
    if not tasks:
        lines.append("NEMA DOVOLJNO PODATAKA U SNAPSHOT-U")
    else:
        for t in tasks[:5]:
            title = t.get("title") or t.get("name") or "NEMA PODATAKA"
            status = t.get("status") or "NEMA PODATAKA"
            priority = t.get("priority") or "NEMA PODATAKA"
            lines.append(f"{title} | {status} | {priority}")

    return "\n".join(lines).strip()


def _coerce_proposed_commands(agent_output: Any) -> List[ProposedAICommand]:
    out: List[ProposedAICommand] = []

    if isinstance(agent_output, dict):
        pcs = agent_output.get("proposed_commands")
    else:
        pcs = getattr(agent_output, "proposed_commands", None)

    if not isinstance(pcs, list):
        return out

    for pc in pcs:
        if isinstance(pc, ProposedAICommand):
            out.append(pc)
            continue
        if isinstance(pc, dict):
            cmd = pc.get("command") or pc.get("command_type") or pc.get("type")
            args = pc.get("args") or pc.get("payload") or {}
            if isinstance(cmd, str) and cmd.strip():
                out.append(
                    ProposedAICommand(
                        command_type=cmd.strip(),
                        payload=args if isinstance(args, dict) else {},
                        status=str(pc.get("status") or "BLOCKED"),
                        required_approval=bool(pc.get("requires_approval", True)),
                        cost_hint=pc.get("cost_hint"),
                        risk_hint=pc.get("risk_hint"),
                    )
                )
    return out


# ======================
# ROUTES
# ======================


@router.get("/status")
async def ceo_console_status() -> Dict[str, Any]:
    """
    Contract:
    - ok: true
    - read_only: key MUST exist
    Ovdje read_only reflektuje default režim modula (executor-friendly => False).
    """
    _ensure_registry_loaded()
    return {
        "ok": True,
        "read_only": False,  # executor-friendly status
        "registry_agents": len(_agent_registry.list_agents() or []),
        "ts": _now_iso(),
    }


@router.post("/command/internal")
async def ceo_command(req: CEOCommandRequest = Body(...)) -> CEOCommandResponse:
    """
    Canon:
    - kada read_only=False: executor-planning mode -> agent treba vratiti proposed_commands (BLOCKED) uz require_approval gate
    - kada read_only=True: advisory mode
    """
    _ensure_registry_loaded()

    initiator = (req.initiator or "ceo_dashboard").strip() or "ceo_dashboard"

    snapshot = _build_snapshot()
    snapshot_meta = {
        "source": "CEOConsoleSnapshotService",
        "ts": _now_iso(),
    }

    preferred_agent_id = _pick_preferred_agent_id(req)

    # Agent input (SSOT snapshot)
    agent_in = AgentInput(
        message=req.text,
        identity_pack={
            "mode": "ADVISOR" if req.read_only else "EXECUTOR",
            "read_only": bool(req.read_only),
            "require_approval": bool(req.require_approval),
        },
        snapshot=snapshot,
        conversation_id=req.session_id,
        history=None,
        preferred_agent_id=preferred_agent_id,
        metadata={
            "initiator": initiator,
            "context_hint": req.context_hint or {},
            "snapshot_meta": snapshot_meta,
            "canon": "ceo_console_router",
            "read_only": bool(req.read_only),
            "require_approval": bool(req.require_approval),
        },
    )

    # Route to agent
    agent_out: Any = None
    try:
        agent_out = await _maybe_await(_agent_router.route(agent_in))
    except Exception:
        agent_out = None

    # Build response
    resp = CEOCommandResponse(
        ok=True,
        read_only=bool(req.read_only),
        context={
            "canon": "ceo_console_router",
            "initiator": initiator,
            "snapshot": snapshot,
            "snapshot_meta": snapshot_meta,
            "read_only": bool(req.read_only),
            "require_approval": bool(req.require_approval),
        },
        trace={
            "selected_by": "preferred_agent_id",
            "preferred_agent_id": preferred_agent_id,
            "normalized_input_text": req.text,
            "normalized_input_source": initiator,
            "normalized_input_has_smart_context": bool(req.context_hint),
            "agent_router_empty_text": False,
        },
    )

    # Text/summary:
    text = None
    if isinstance(agent_out, dict):
        text = agent_out.get("text") or agent_out.get("summary")
    else:
        text = getattr(agent_out, "text", None) or getattr(agent_out, "summary", None)

    if isinstance(text, str) and text.strip():
        resp.summary = text.strip()
    else:
        # samo fallback (ako agent baš ništa ne vrati)
        resp.summary = _format_summary_from_snapshot(snapshot)

    # Proposed commands (ključ za execution flow)
    resp.proposed_commands = _coerce_proposed_commands(agent_out)

    return resp


# (Opcionalno) alias bez "/internal" ako ti gateway direktno mapira:
@router.post("/command")
async def ceo_command_alias(req: CEOCommandRequest = Body(...)) -> CEOCommandResponse:
    return await ceo_command(req)
