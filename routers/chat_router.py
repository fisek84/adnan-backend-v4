from __future__ import annotations

import inspect
from typing import Any, Dict

from fastapi import APIRouter

from models.agent_contract import AgentInput, AgentOutput
from services.agent_router_service import AgentRouterService


def build_chat_router(agent_router: AgentRouterService) -> APIRouter:
    """
    Builds the canonical chat router.

    Canon:
      - Route path is "/chat"
      - Mount with prefix="/api" => final endpoint is "/api/chat"

    Canonical guarantees:
      - READ/PROPOSE ONLY boundary
      - Defense-in-depth: enforce read_only on both input metadata and output envelope
      - Fail-soft: never crash due to missing optional fields (trace, proposed_commands, metadata)
    """
    router = APIRouter()

    def _ensure_dict(v: Any) -> Dict[str, Any]:
        return v if isinstance(v, dict) else {}

    def _enforce_input_read_only(payload: AgentInput) -> None:
        md = _ensure_dict(getattr(payload, "metadata", None))
        # Hard-enforce read-only semantics at the boundary.
        md["read_only"] = True
        md["endpoint"] = "/api/chat"
        md["canon"] = "read_propose_only"
        payload.metadata = md  # type: ignore[assignment]

    def _enforce_output_read_only(out: AgentOutput) -> AgentOutput:
        # Final hard gate (defense-in-depth)
        out.read_only = True

        trace = _ensure_dict(getattr(out, "trace", None))
        trace["endpoint"] = "/api/chat"
        trace["canon"] = "read_propose_only"
        out.trace = trace  # type: ignore[assignment]

        pcs = getattr(out, "proposed_commands", None) or []
        for pc in pcs:
            # Ensure any proposed action is non-executing / dry-run.
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
                # fail-soft: do not break the chat endpoint due to a command shape mismatch
                continue

        out.proposed_commands = pcs  # type: ignore[assignment]
        return out

    @router.post("/chat", response_model=AgentOutput)
    async def canonical_chat_endpoint(payload: AgentInput) -> AgentOutput:
        """
        CANONICAL CHAT ENDPOINT — READ/PROPOSE ONLY.

        Hard rules:
        - never executes commands
        - never creates approvals
        - only returns text + proposed_commands[] (dry-run)
        """
        _enforce_input_read_only(payload)

        routed = agent_router.route(payload)
        if inspect.isawaitable(routed):
            routed = await routed  # type: ignore[assignment]

        out = routed  # type: ignore[assignment]
        return _enforce_output_read_only(out)

    return router
