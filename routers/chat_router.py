# routers/chat_router.py

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter

from models.agent_contract import AgentInput, AgentOutput
from services.ceo_advisor_agent import create_ceo_advisor_agent
from services.knowledge_snapshot_service import KnowledgeSnapshotService

# Must match gateway_server.PROPOSAL_WRAPPER_INTENT
PROPOSAL_WRAPPER_INTENT = "ceo.command.propose"


def build_chat_router(agent_router: Optional[Any] = None) -> APIRouter:
    """
    /api/chat je READ/PROPOSE ONLY.
    - nikad ne izvršava side-effect
    - injektuje server snapshot ako klijent ne pošalje snapshot
    """

    router = APIRouter()

    def _ensure_dict(v: Any) -> Dict[str, Any]:
        return v if isinstance(v, dict) else {}

    def _snapshot_meta(snap: Dict[str, Any]) -> Dict[str, Any]:
        if not isinstance(snap, dict):
            return {"is_empty": True}
        return {
            "is_empty": not bool(snap),
            "last_sync": snap.get("last_sync"),
            "ready": snap.get("ready"),
            "keys": sorted(list(snap.keys())) if isinstance(snap, dict) else [],
        }

    def _enforce_input_read_only(payload: AgentInput) -> None:
        md = _ensure_dict(getattr(payload, "metadata", None))
        md["read_only"] = True
        md["require_approval"] = True
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
                md["snapshot_meta"] = _snapshot_meta(snap)
                payload.metadata = md  # type: ignore[assignment]
                return

            server_snap = KnowledgeSnapshotService.get_snapshot() or {}
            payload.snapshot = server_snap  # type: ignore[assignment]

            md = _ensure_dict(getattr(payload, "metadata", None))
            md["snapshot_source"] = "server"
            md["snapshot_meta"] = _snapshot_meta(server_snap)
            payload.metadata = md  # type: ignore[assignment]
        except Exception:
            md = _ensure_dict(getattr(payload, "metadata", None))
            md["snapshot_source"] = md.get("snapshot_source") or "error"
            md["snapshot_meta"] = md.get("snapshot_meta") or {
                "is_empty": True,
                "error": True,
            }
            payload.metadata = md  # type: ignore[assignment]

    def _extract_prompt(payload: AgentInput) -> str:
        for k in ("message", "text", "input_text", "prompt"):
            v = getattr(payload, k, None)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def _inject_fallback_proposed_commands(out: AgentOutput, *, prompt: str) -> None:
        """
        Frontend expects proposed_commands as OPAQUE execute/raw payloads.
        We provide a wrapper command that gateway_server.execute_raw_command can unwrap:
          command=intent="ceo.command.propose"
          params={"prompt": "..."}
        """
        pcs = getattr(out, "proposed_commands", None) or []
        if isinstance(pcs, dict):
            pcs = []

        if isinstance(pcs, list) and len(pcs) > 0:
            return

        safe_prompt = (prompt or "").strip() or "noop"

        out.proposed_commands = [
            {
                # execute/raw payload (opaque for frontend)
                "command": PROPOSAL_WRAPPER_INTENT,
                "intent": PROPOSAL_WRAPPER_INTENT,
                "params": {"prompt": safe_prompt},
                "initiator": "ceo",
                "read_only": False,
                "metadata": {
                    "source": "ceo_console",
                    "canon": "CEO_CONSOLE_EXECUTION_FLOW",
                    "endpoint": "/api/execute/raw",
                },
            }
        ]

        tr = _ensure_dict(getattr(out, "trace", None))
        tr["fallback_proposed_commands"] = True
        tr["router_version"] = "chat-fallback-proposals-v2"
        out.trace = tr  # type: ignore[assignment]

    def _enforce_output_read_only(out: AgentOutput, payload: AgentInput) -> AgentOutput:
        out.read_only = True

        trace = _ensure_dict(getattr(out, "trace", None))
        trace["endpoint"] = "/api/chat"
        trace["canon"] = "read_propose_only"

        md = _ensure_dict(getattr(payload, "metadata", None))
        trace["snapshot_source"] = md.get("snapshot_source")
        trace["snapshot_meta"] = md.get("snapshot_meta")

        out.trace = trace  # type: ignore[assignment]

        pcs = getattr(out, "proposed_commands", None) or []
        if isinstance(pcs, dict):
            pcs = []

        # NOTE: proposals are dicts; keep them as-is (opaque).
        out.proposed_commands = pcs  # type: ignore[assignment]
        return out

    async def _call_agent(payload: AgentInput) -> AgentOutput:
        if agent_router and hasattr(agent_router, "route"):
            try:
                out = await agent_router.route(payload)  # type: ignore[attr-defined]
                if isinstance(out, AgentOutput):
                    return out
            except Exception:
                pass

        ctx: Dict[str, Any] = {"trace": {"selected_by": "chat_router_direct"}}
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

        out = await _call_agent(payload)

        prompt = _extract_prompt(payload)
        _inject_fallback_proposed_commands(out, prompt=prompt)

        return _enforce_output_read_only(out, payload)

    return router
