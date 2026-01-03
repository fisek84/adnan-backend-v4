from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter

from models.agent_contract import AgentInput, AgentOutput
from services.knowledge_snapshot_service import KnowledgeSnapshotService
from services.ceo_advisor_agent import create_ceo_advisor_agent


def build_chat_router(_agent_router=None) -> APIRouter:
    router = APIRouter()

    def _ensure_dict(v: Any) -> Dict[str, Any]:
        return v if isinstance(v, dict) else {}

    def _enforce_input_read_only(payload: AgentInput) -> None:
        md = _ensure_dict(getattr(payload, "metadata", None))
        md["read_only"] = True
        md["endpoint"] = "/api/chat"
        md["canon"] = "read_propose_only"
        payload.metadata = md  # type: ignore[assignment]

        if hasattr(payload, "read_only"):
            try:
                payload.read_only = True  # type: ignore[attr-defined]
            except Exception:
                pass

    def _inject_server_snapshot_if_missing(payload: AgentInput) -> None:
        try:
            snap = getattr(payload, "snapshot", None)
            if isinstance(snap, dict) and snap:
                md = _ensure_dict(getattr(payload, "metadata", None))
                md.setdefault("snapshot_source", "client")
                payload.metadata = md  # type: ignore[assignment]
                return

            payload.snapshot = KnowledgeSnapshotService.get_snapshot() or {}  # type: ignore[assignment]
            md = _ensure_dict(getattr(payload, "metadata", None))
            md["snapshot_source"] = "server"
            payload.metadata = md  # type: ignore[assignment]
        except Exception:
            # fail-soft
            pass

    def _enforce_output_read_only(out: AgentOutput) -> AgentOutput:
        out.read_only = True

        trace = _ensure_dict(getattr(out, "trace", None))
        trace["endpoint"] = "/api/chat"
        trace["canon"] = "read_propose_only"
        out.trace = trace  # type: ignore[assignment]

        pcs = getattr(out, "proposed_commands", None) or []
        if isinstance(pcs, dict):
            pcs = []

        for pc in pcs:
            try:
                if hasattr(pc, "dry_run"):
                    pc.dry_run = True
                if hasattr(pc, "execute"):
                    pc.execute = False
                if hasattr(pc, "approved"):
                    pc.approved = False
                if hasattr(pc, "requires_approval"):
                    pc.requires_approval = True
            except Exception:
                continue

        out.proposed_commands = pcs  # type: ignore[assignment]
        return out

    async def _call_ceo_advisor(payload: AgentInput) -> AgentOutput:
        # create_ceo_advisor_agent je ASYNC funkcija sa (agent_input, ctx)
        ctx: Dict[str, Any] = {
            "trace": {"selected_by": "chat_router_direct"},
        }
        out = await create_ceo_advisor_agent(payload, ctx)

        if isinstance(out, AgentOutput):
            return out

        return AgentOutput(
            text="CEO Advisor failed.",
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={
                "error": "CEO advisor did not return AgentOutput",
                "endpoint": "/api/chat",
                "canon": "read_propose_only",
            },
        )

    @router.post("/chat", response_model=AgentOutput)
    async def chat(payload: AgentInput) -> AgentOutput:
        _enforce_input_read_only(payload)
        _inject_server_snapshot_if_missing(payload)

        out = await _call_ceo_advisor(payload)
        return _enforce_output_read_only(out)

    return router
