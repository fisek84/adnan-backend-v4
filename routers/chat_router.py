# routers/chat_router.py

from __future__ import annotations

from typing import Any, Dict, Optional, List

from fastapi import APIRouter

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
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

    def _snapshot_meta(
        *, wrapper: Dict[str, Any], payload: Dict[str, Any]
    ) -> Dict[str, Any]:
        w = wrapper if isinstance(wrapper, dict) else {}
        p = payload if isinstance(payload, dict) else {}
        return {
            "is_empty": not bool(p),
            "last_sync": w.get("last_sync"),
            "ready": w.get("ready"),
            "payload_keys": sorted(list(p.keys())) if isinstance(p, dict) else [],
            "wrapper_keys": sorted(list(w.keys())) if isinstance(w, dict) else [],
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
        """
        CRITICAL:
        AgentInput.snapshot MUST be SSOT payload (KnowledgeSnapshotService.get_payload()).
        Wrapper (ready/last_sync/trace) ide u metadata.snapshot_meta.
        """
        try:
            snap = getattr(payload, "snapshot", None)
            if isinstance(snap, dict) and snap:
                md = _ensure_dict(getattr(payload, "metadata", None))
                md.setdefault("snapshot_source", "client")
                md["snapshot_meta"] = _snapshot_meta(wrapper={}, payload=snap)
                payload.metadata = md  # type: ignore[assignment]
                return

            wrapper: Dict[str, Any] = {}
            payload_dict: Dict[str, Any] = {}

            # Wrapper (ready/last_sync/trace)
            try:
                wrapper = KnowledgeSnapshotService.get_snapshot() or {}
                if not isinstance(wrapper, dict):
                    wrapper = {}
            except Exception:
                wrapper = {}

            # SSOT payload (goals/tasks/projects/...)
            try:
                get_payload = getattr(KnowledgeSnapshotService, "get_payload", None)
                if callable(get_payload):
                    payload_dict = get_payload() or {}
                else:
                    payload_dict = (
                        wrapper.get("payload")
                        if isinstance(wrapper.get("payload"), dict)
                        else {}
                    )
                if not isinstance(payload_dict, dict):
                    payload_dict = {}
            except Exception:
                payload_dict = {}

            payload.snapshot = payload_dict  # type: ignore[assignment]

            md = _ensure_dict(getattr(payload, "metadata", None))
            md["snapshot_source"] = "server"
            md["snapshot_meta"] = _snapshot_meta(wrapper=wrapper, payload=payload_dict)
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

    def _normalize_proposed_commands(raw: Any) -> List[ProposedCommand]:
        """
        CANON for /api/chat:
        - proposed_commands MUST serialize to list[dict] with dry_run=True
        - internally keep List[ProposedCommand] to avoid pydantic serializer warnings
        - accept legacy 'params' alias -> normalize to 'args' via ProposedCommand validators
        """
        if raw is None:
            return []
        if isinstance(raw, dict):
            return []

        items = raw if isinstance(raw, list) else []
        out: List[ProposedCommand] = []

        for item in items:
            try:
                # Pydantic v2: ProposedCommand.model_validate
                if hasattr(ProposedCommand, "model_validate"):
                    pc = ProposedCommand.model_validate(item)  # type: ignore[attr-defined]
                else:
                    pc = ProposedCommand.parse_obj(item)  # type: ignore[attr-defined]
            except Exception:
                # Last resort: construct minimal compliant proposal
                d = item if isinstance(item, dict) else {}
                # alias params -> args
                args = d.get("args")
                if not isinstance(args, dict) and isinstance(d.get("params"), dict):
                    args = d.get("params") or {}
                if not isinstance(args, dict):
                    args = {}

                cmd = str(d.get("command") or "").strip() or PROPOSAL_WRAPPER_INTENT
                pc = ProposedCommand(command=cmd, args=args)

            # Defense-in-depth: /api/chat is always dry_run
            try:
                pc.dry_run = True  # type: ignore[assignment]
            except Exception:
                pass

            out.append(pc)

        return out

    def _inject_fallback_proposed_commands(out: AgentOutput, *, prompt: str) -> None:
        """
        Frontend expects proposed_commands as OPAQUE execute/raw payloads.
        Provide wrapper command that /api/execute/raw can unwrap:
          command=intent="ceo.command.propose"
          args(params alias)={"prompt": "..."}
        """
        pcs = getattr(out, "proposed_commands", None) or []
        if isinstance(pcs, dict):
            pcs = []

        if isinstance(pcs, list) and len(pcs) > 0:
            return

        safe_prompt = (prompt or "").strip() or "noop"

        # Keep ProposedCommand instances (no serializer warnings)
        out.proposed_commands = [
            ProposedCommand(
                command=PROPOSAL_WRAPPER_INTENT,
                args={"prompt": safe_prompt},
                reason="Fallback proposal (no agent proposals returned).",
                dry_run=True,
                requires_approval=True,
                risk="LOW",
                scope="api_execute_raw",
                payload_summary={
                    "endpoint": "/api/execute/raw",
                    "canon": "CEO_CONSOLE_EXECUTION_FLOW",
                    "source": "ceo_console",
                },
            )
        ]

        tr = _ensure_dict(getattr(out, "trace", None))
        tr["fallback_proposed_commands"] = True
        tr["router_version"] = "chat-fallback-proposals-v3"
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

        pcs = getattr(out, "proposed_commands", None)
        out.proposed_commands = _normalize_proposed_commands(pcs)

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
