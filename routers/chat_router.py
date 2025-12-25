from __future__ import annotations

from fastapi import APIRouter

from models.agent_contract import AgentInput, AgentOutput
from services.agent_router_service import AgentRouterService


def build_chat_router(agent_router: AgentRouterService) -> APIRouter:
    """
    Builds the canonical chat router.

    IMPORTANT:
    - Do NOT mount this router with prefix="/api" in gateway_server.py
      if you keep the route path as "/api/chat".
    - Either:
        A) route="/chat" + mount prefix="/api"
      OR
        B) route="/api/chat" + mount with no prefix

    This file implements option A (canonical, avoids double /api/api).
    """
    router = APIRouter()

    @router.post("/chat", response_model=AgentOutput)
    def canonical_chat_endpoint(payload: AgentInput) -> AgentOutput:
        """
        CANONICAL CHAT ENDPOINT — READ/PROPOSE ONLY.

        Hard rules:
        - never executes commands
        - never creates approvals
        - only returns text + proposed_commands[]
        """
        # Hard-enforce read-only semantics at the boundary.
        if payload.metadata is None:
            payload.metadata = {}
        payload.metadata["read_only"] = True
        payload.metadata["endpoint"] = "/api/chat"

        out = agent_router.route(payload)

        # Final hard gate (defense-in-depth)
        out.read_only = True
        if out.trace is None:
            out.trace = {}
        out.trace["endpoint"] = "/api/chat"
        out.trace["canon"] = "read_propose_only"

        for pc in out.proposed_commands or []:
            pc.dry_run = True

        return out

    return router
