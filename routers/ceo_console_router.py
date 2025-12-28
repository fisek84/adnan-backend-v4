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


def _prop_text(item: Dict[str, Any], candidates: List[str]) -> Optional[str]:
    """
    Supports:
      - compact Notion pages: {"properties": {"Name": "...", "Status": "...", ...}}
      - fallback structures where fields are top-level.
    """
    if not isinstance(item, dict):
        return None

    # 1) top-level direct
    for k in candidates:
        v = item.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()

    # 2) properties dict (canonical from NotionService._compact_page)
    props = item.get("properties")
    if isinstance(props, dict):
        # exact match
        for k in candidates:
            v = props.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()

        # case-insensitive match
        lower_map = {str(pk).lower(): pv for pk, pv in props.items()}
        for k in candidates:
            v = lower_map.get(str(k).lower())
            if isinstance(v, str) and v.strip():
                return v.strip()

    return None


def _compact_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalizes a Notion compact page into what CEO Advisor expects.
    Ensures required fields exist (title/status/priority) to prevent LLM fallbacks
    leaking into structured output.
    """
    title = _prop_text(item, ["title", "name", "Name", "Title", "Naziv", "Ime"])
    status = _prop_text(item, ["status", "Status"])
    priority = _prop_text(item, ["priority", "Priority", "Prioritet"])

    out: Dict[str, Any] = {"id": item.get("id")}

    # Always include fields with safe defaults
    out["title"] = title or "NEMA PODATAKA"
    out["name"] = out["title"]  # compatibility
    out["status"] = status or "NEMA PODATAKA"
    out["priority"] = priority or "NEMA PODATAKA"

    if item.get("url"):
        out["url"] = item.get("url")

    return out


def _compact_dashboard_snapshot(snap: Dict[str, Any]) -> Dict[str, Any]:
    dashboard = snap.get("dashboard", {}) if isinstance(snap, dict) else {}
    goals_raw = dashboard.get("goals", []) if isinstance(dashboard, dict) else []
    tasks_raw = dashboard.get("tasks", []) if isinstance(dashboard, dict) else []

    if not isinstance(goals_raw, list):
        goals_raw = []
    if not isinstance(tasks_raw, list):
        tasks_raw = []

    out: Dict[str, Any] = {
        "available": True,
        "source": snap.get("source"),
        "kind": "dashboard_snapshot",
        "dashboard": {
            "goals": [_compact_item(g) for g in goals_raw if isinstance(g, dict)],
            "tasks": [_compact_item(t) for t in tasks_raw if isinstance(t, dict)],
        },
    }

    # Optional extras (safe to attach)
    identity_pack = snap.get("identity_pack")
    if isinstance(identity_pack, dict):
        out["identity_pack"] = identity_pack

    if "knowledge_ready" in snap:
        out["knowledge_ready"] = bool(snap.get("knowledge_ready"))
    if snap.get("knowledge_last_sync") is not None:
        out["knowledge_last_sync"] = snap.get("knowledge_last_sync")

    return out


def _build_dashboard_from_system_snapshot(sys_snap: Dict[str, Any]) -> Dict[str, Any]:
    """
    SystemReadExecutor.snapshot() -> { "knowledge_snapshot": { "databases": {goals,tasks,...} }, "ceo_notion_snapshot": {...} }
    Prefer KnowledgeSnapshotService data (populated by refresh_snapshot).
    """
    dashboard: Dict[str, Any] = {"goals": [], "tasks": []}

    ks = sys_snap.get("knowledge_snapshot") if isinstance(sys_snap, dict) else None
    dbs = (ks or {}).get("databases") if isinstance(ks, dict) else None

    if isinstance(dbs, dict):
        goals = dbs.get("goals") or []
        tasks = dbs.get("tasks") or []
        if isinstance(goals, list):
            dashboard["goals"] = goals
        if isinstance(tasks, list):
            dashboard["tasks"] = tasks

    # If knowledge snapshot has nothing, try ceo_notion_snapshot as a legacy fallback
    if not dashboard["goals"] and not dashboard["tasks"]:
        ceo_ns = (
            sys_snap.get("ceo_notion_snapshot") if isinstance(sys_snap, dict) else None
        )
        if isinstance(ceo_ns, dict) and isinstance(ceo_ns.get("dashboard"), dict):
            d = ceo_ns.get("dashboard") or {}
            goals2 = d.get("goals") or []
            tasks2 = d.get("tasks") or []
            if isinstance(goals2, list):
                dashboard["goals"] = goals2
            if isinstance(tasks2, list):
                dashboard["tasks"] = tasks2

    return dashboard


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
            return ctx  # do not call server snapshot

    # ===============================
    # FALLBACK: CANONICAL SERVER SNAPSHOT (SystemReadExecutor)
    # ===============================
    try:
        from services.system_read_executor import SystemReadExecutor

        sys_exec = SystemReadExecutor()
        sys_snap = sys_exec.snapshot()
        sys_snap = await _maybe_await(sys_snap)

        dashboard = _build_dashboard_from_system_snapshot(sys_snap)

        identity_pack = (
            sys_snap.get("identity_pack") if isinstance(sys_snap, dict) else None
        )
        ks = sys_snap.get("knowledge_snapshot") if isinstance(sys_snap, dict) else None

        compact = _compact_dashboard_snapshot(
            {
                "source": "SystemReadExecutor",
                "dashboard": dashboard,
                "identity_pack": identity_pack
                if isinstance(identity_pack, dict)
                else {},
                "knowledge_ready": bool(ks.get("ready"))
                if isinstance(ks, dict)
                else False,
                "knowledge_last_sync": ks.get("last_sync")
                if isinstance(ks, dict)
                else None,
            }
        )

        ctx["snapshot"] = compact
        ctx["snapshot_meta"] = {
            "snapshotter": "SystemReadExecutor",
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

    proposed: List[ProposedAICommand] = []
    for p in out.proposed_commands or []:
        if not p.command:
            continue

        payload = p.args or {}
        # FIX: ensure refresh_snapshot proposal has a usable payload
        if p.command == "refresh_snapshot" and (
            not isinstance(payload, dict) or not payload
        ):
            payload = {"source": "ceo_dashboard"}

        proposed.append(
            ProposedAICommand(
                command_type=p.command,
                payload=payload if isinstance(payload, dict) else {},
            )
        )

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
