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


@router.post("/command/internal")
async def ceo_command(req: CEOCommandRequest = Body(...)) -> CEOCommandResponse:
    _ensure_registry_loaded()

    agent_input = AgentInput(
        message=req.text,
        snapshot=KnowledgeSnapshotService.get_payload() or {},
        metadata={
            "initiator": req.initiator or "ceo",
            "read_only": True,
            "require_approval": bool(req.require_approval),
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
        trace={},
    )

    _inject_confidence_risk(resp)
    return resp


@router.post("/command")
async def ceo_command_alias(req: CEOCommandRequest = Body(...)) -> CEOCommandResponse:
    return await ceo_command(req)
