from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Literal

from fastapi import APIRouter, Body
from pydantic import BaseModel, Field

try:
    from pydantic import model_validator  # type: ignore

    _PYDANTIC_V2 = True
except Exception:
    _PYDANTIC_V2 = False
    from pydantic import root_validator  # type: ignore

from models.agent_contract import AgentInput
from services.agent_registry_service import AgentRegistryService
from services.agent_router_service import AgentRouterService
from services.knowledge_snapshot_service import KnowledgeSnapshotService

try:
    from services.identity_resolver import lookup_identity_id as _lookup_identity_id  # type: ignore
except Exception:  # pragma: no cover
    _lookup_identity_id = None  # type: ignore

ROUTER_VERSION = "2026-01-06-canon-read-propose-only-v1"

router = APIRouter(prefix="/ceo-console", tags=["CEO Console"])

_agent_registry = AgentRegistryService()
_agent_router = AgentRouterService(_agent_registry)


def _ensure_registry_loaded() -> None:
    try:
        if not _agent_registry.list_agents():
            _agent_registry.load_from_agents_json("config/agents.json", clear=True)
    except Exception:
        pass


class CEOCommandRequest(BaseModel):
    text: str = Field(..., min_length=1)
    initiator: Optional[str] = None
    session_id: Optional[str] = None
    context_hint: Optional[Dict[str, Any]] = None
    read_only: Optional[bool] = None
    require_approval: Optional[bool] = None
    preferred_agent_id: Optional[str] = None

    if _PYDANTIC_V2:

        @model_validator(mode="before")
        @classmethod
        def _normalize(cls, v: Any) -> Any:
            if not isinstance(v, dict):
                return v
            for k in ("text", "prompt", "input_text", "message"):
                if isinstance(v.get(k), str) and v[k].strip():
                    v["text"] = v[k].strip()
                    return v
            return v
    else:

        @root_validator(pre=True)
        def _normalize(cls, v: Any) -> Any:
            if not isinstance(v, dict):
                return v
            for k in ("text", "prompt", "input_text", "message"):
                if isinstance(v.get(k), str) and v[k].strip():
                    v["text"] = v[k].strip()
                    return v
            return v


RiskLevel = Literal["low", "medium", "high"]


class CEOCommandResponse(BaseModel):
    ok: bool = True
    read_only: bool = True
    summary: str = ""
    proposed_commands: List[Dict[str, Any]] = Field(default_factory=list)
    context: Dict[str, Any] = Field(default_factory=dict)
    trace: Dict[str, Any] = Field(default_factory=dict)
    confidence_risk: Dict[str, Any] = Field(default_factory=dict)


def _maybe_await(v: Any) -> Any:
    if inspect.isawaitable(v):
        return v
    return v


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _extract_proposed_commands(agent_out: Any) -> List[Dict[str, Any]]:
    pcs = (
        agent_out.get("proposed_commands")
        if isinstance(agent_out, dict)
        else getattr(agent_out, "proposed_commands", None)
    )
    return [x for x in pcs if isinstance(x, dict)] if isinstance(pcs, list) else []


def _compute_risk_level(proposed: List[Dict[str, Any]]) -> RiskLevel:
    for pc in proposed:
        if pc.get("requires_approval") is True:
            return "high"
        if pc.get("risk") == "HIGH":
            return "high"
        if pc.get("risk") == "MED":
            return "medium"
    return "low"


def _compute_confidence_score(risk: RiskLevel) -> float:
    base = 0.9
    if risk == "medium":
        base -= 0.2
    elif risk == "high":
        base -= 0.4
    return max(0.0, min(1.0, base))


# ============================================================
# 🔴 KLJUČNA POPRAVKA JE OVDJE
# ============================================================
def _inject_confidence_risk(resp: CEOCommandResponse) -> None:
    proposed = resp.proposed_commands or []
    risk_level = _compute_risk_level(proposed)
    confidence_score = _compute_confidence_score(risk_level)

    payload = {
        "confidence_score": confidence_score,
        "assumption_count": 0,
        "recommendation_type": "OPERATIONAL",
    }

    resp.confidence_risk = {
        **payload,
        "risk_level": risk_level,
    }

    # 🔴 OVO JE NEDOSTAJALO – injekcija u proposal
    for pc in resp.proposed_commands:
        ps = pc.get("payload_summary")
        if not isinstance(ps, dict):
            ps = {}
        ps.update(payload)
        pc["payload_summary"] = ps

        # osiguraj risk na top-level
        pc.setdefault("risk", risk_level.upper())


def _attach_trace_contract_fields(
    resp: CEOCommandResponse,
    *,
    grounding_pack: Dict[str, Any],
    identity_pack: Dict[str, Any],
    knowledge_snapshot: Dict[str, Any],
    memory_public: Dict[str, Any],
) -> None:
    tr = resp.trace if isinstance(resp.trace, dict) else {}

    gp_trace = (
        grounding_pack.get("trace")
        if isinstance(grounding_pack.get("trace"), dict)
        else {}
    )
    used_raw = (
        gp_trace.get("used_sources")
        if isinstance(gp_trace.get("used_sources"), list)
        else []
    )
    used_raw = [x for x in used_raw if isinstance(x, str) and x.strip()]

    mapping = {
        "kb_snapshot": "kb",
        "memory_snapshot": "memory",
    }
    used_sources = sorted({mapping.get(x, x) for x in used_raw})

    # Optional read-only DB identity signal: only mark as used when we
    # successfully resolved a DB identity id (no implicit writes).
    try:
        iid = (
            identity_pack.get("identity_id_db")
            if isinstance(identity_pack, dict)
            else None
        )
        if isinstance(iid, str) and iid.strip():
            used_sources = sorted({*used_sources, "identity_root"})
    except Exception:
        pass

    missing_inputs: List[str] = []

    if not (
        isinstance(identity_pack, dict) and identity_pack.get("available") is not False
    ):
        missing_inputs.append("identity_pack")

    if not (
        isinstance(knowledge_snapshot, dict) and knowledge_snapshot.get("ready") is True
    ):
        missing_inputs.append("notion_snapshot")

    gp_enabled = (
        grounding_pack.get("enabled") is True
        if isinstance(grounding_pack, dict)
        else False
    )
    if not gp_enabled:
        missing_inputs.append("kb")

    if not (isinstance(memory_public, dict) and memory_public):
        missing_inputs.append("memory")

    kb_ids_used: List[str] = []
    kb = (
        grounding_pack.get("kb_retrieved")
        if isinstance(grounding_pack.get("kb_retrieved"), dict)
        else {}
    )
    raw_ids = kb.get("used_entry_ids") if isinstance(kb, dict) else None
    if isinstance(raw_ids, list):
        kb_ids_used = [x for x in raw_ids if isinstance(x, str) and x.strip()]

    tr["used_sources"] = used_sources
    tr["missing_inputs"] = sorted(
        {x for x in missing_inputs if isinstance(x, str) and x.strip()}
    )
    tr["kb_ids_used"] = kb_ids_used

    resp.trace = tr


@router.post("/command/internal")
async def ceo_command(req: CEOCommandRequest = Body(...)) -> CEOCommandResponse:
    _ensure_registry_loaded()

    # ------------------------------------------------------------
    # Build CEO Advisor intelligence context (runtime SSOT)
    # - identity_pack (SystemReadExecutor)
    # - memory snapshot (ReadOnlyMemoryService)
    # - conversation_state (ConversationStateStore)
    # - grounding_pack (GroundingPackService)
    # ------------------------------------------------------------
    session_id = (
        req.session_id
        if isinstance(req.session_id, str) and req.session_id.strip()
        else None
    )

    identity_pack: Dict[str, Any] = {}
    try:
        from services.system_read_executor import SystemReadExecutor  # type: ignore

        sys_snap = SystemReadExecutor().snapshot()
        ip = sys_snap.get("identity_pack") if isinstance(sys_snap, dict) else None
        identity_pack = ip if isinstance(ip, dict) else {}
    except Exception:
        identity_pack = {}

    # Read-only Postgres lookup (no INSERT). Fail-safe if DB/migrations missing.
    try:
        if callable(_lookup_identity_id) and isinstance(identity_pack, dict):
            iid = _lookup_identity_id("CEO")
            if isinstance(iid, str) and iid.strip():
                identity_pack.setdefault("identity_id_db", iid)
    except Exception:
        pass

    memory_public: Dict[str, Any] = {}
    try:
        from services.memory_read_only import ReadOnlyMemoryService  # type: ignore

        memory_public = ReadOnlyMemoryService().export_public_snapshot()
        if not isinstance(memory_public, dict):
            memory_public = {}
    except Exception:
        memory_public = {}

    conversation_state: Optional[str] = None
    if session_id:
        try:
            from services.ceo_conversation_state_store import ConversationStateStore  # type: ignore

            cs = ConversationStateStore.get_summary(conversation_id=session_id)
            conversation_state = (
                cs.summary_text if hasattr(cs, "summary_text") else None
            )
        except Exception:
            conversation_state = None

    knowledge_snapshot = KnowledgeSnapshotService.get_snapshot() or {}

    grounding_pack: Dict[str, Any] = {}
    try:
        from services.grounding_pack_service import GroundingPackService  # type: ignore

        grounding_pack = GroundingPackService.build(
            prompt=req.text,
            knowledge_snapshot=knowledge_snapshot,
            memory_public_snapshot=memory_public,
            legacy_trace={"source": "ceo_console_router"},
            agent_id="ceo_advisor",
        )
        if not isinstance(grounding_pack, dict):
            grounding_pack = {}
    except Exception:
        grounding_pack = {}

    # Normalize KB payload presence (runtime contract): even if empty, provide a
    # stable kb object so downstream trace semantics can distinguish
    # "provided but empty" from "missing".
    kb_payload: Dict[str, Any] = {}
    try:
        gp_kb = (
            grounding_pack.get("kb_retrieved")
            if isinstance(grounding_pack.get("kb_retrieved"), dict)
            else None
        )

        if not isinstance(gp_kb, dict):
            gp_kb = {"used_entry_ids": [], "entries": [], "refs": []}
            grounding_pack["kb_retrieved"] = gp_kb

        used_ids = gp_kb.get("used_entry_ids")
        if not isinstance(used_ids, list):
            used_ids = []
            gp_kb["used_entry_ids"] = used_ids

        entries = gp_kb.get("entries")
        if not isinstance(entries, list):
            entries = []
            gp_kb["entries"] = entries

        kb_payload = {
            "used_entry_ids": [x for x in used_ids if isinstance(x, str) and x.strip()],
            "entries": [e for e in entries if isinstance(e, dict)],
            "refs": gp_kb.get("refs") if isinstance(gp_kb.get("refs"), list) else [],
        }
    except Exception:
        kb_payload = {"used_entry_ids": [], "entries": [], "refs": []}

    agent_input = AgentInput(
        message=req.text,
        snapshot=knowledge_snapshot,
        identity_pack=identity_pack,
        preferred_agent_id=req.preferred_agent_id or "ceo_advisor",
        metadata={
            "initiator": req.initiator or "ceo",
            "read_only": True,
            "require_approval": bool(req.require_approval),
            "snapshot_source": "KnowledgeSnapshotService.get_snapshot",
            "session_id": session_id,
            "agent_ctx": {
                "grounding_pack": grounding_pack,
                "memory": memory_public,
                "conversation_state": conversation_state,
                "kb": kb_payload,
            },
        },
    )

    agent_out = await _maybe_await(_agent_router.route(agent_input))

    proposed = _extract_proposed_commands(agent_out)
    summary = (
        agent_out.get("text", "")
        if isinstance(agent_out, dict)
        else getattr(agent_out, "text", "")
    )

    resp = CEOCommandResponse(
        ok=True,
        read_only=True,
        summary=summary,
        proposed_commands=proposed,
        context={"canon": "read_propose_only"},
        trace=(
            agent_out.get("trace", {})
            if isinstance(agent_out, dict)
            else (
                getattr(agent_out, "trace", {})
                if isinstance(getattr(agent_out, "trace", None), dict)
                else {}
            )
        ),
    )

    _attach_trace_contract_fields(
        resp,
        grounding_pack=grounding_pack,
        identity_pack=identity_pack,
        knowledge_snapshot=knowledge_snapshot
        if isinstance(knowledge_snapshot, dict)
        else {},
        memory_public=memory_public,
    )

    _inject_confidence_risk(resp)
    return resp


@router.post("/command")
async def ceo_command_alias(req: CEOCommandRequest = Body(...)) -> CEOCommandResponse:
    return await ceo_command(req)
