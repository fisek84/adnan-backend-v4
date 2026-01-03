from __future__ import annotations

import inspect
from typing import Any, Dict

from fastapi import APIRouter

from models.agent_contract import AgentInput, AgentOutput
from services.agent_router_service import AgentRouterService
from services.knowledge_snapshot_service import KnowledgeSnapshotService


def build_chat_router(agent_router: AgentRouterService) -> APIRouter:
    """
    Builds the canonical chat router.

    Canon:
      - Route path is "/chat"
      - Mount with prefix="/api" => final endpoint is "/api/chat"

    Canonical guarantees:
      - READ/PROPOSE ONLY boundary
      - Hard-route to CEO Advisor (chat/propose agent), never ExecutionOrchestrator
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

        # CRITICAL: force chat agent selection to CEO Advisor.
        # We set multiple common "hint" keys to be robust across router implementations.
        md["force_agent_id"] = "ceo_advisor"
        md["agent_id"] = "ceo_advisor"
        md["preferred_agent_id"] = "ceo_advisor"
        md["selected_agent_id"] = "ceo_advisor"
        md["force_entrypoint"] = "services.ceo_advisor_agent:CEOAdvisorAgent"
        md["chat_agent"] = "ceo_advisor"

        payload.metadata = md  # type: ignore[assignment]

        # Defense-in-depth: if model has a read_only field, force it too.
        if hasattr(payload, "read_only"):
            try:
                payload.read_only = True  # type: ignore[attr-defined]
            except Exception:
                pass

    def _inject_server_snapshot_if_missing(payload: AgentInput) -> None:
        """
        If the client didn't provide a snapshot (or it is empty / invalid),
        inject the latest server-side snapshot into the payload.

        Fail-soft: never crash /api/chat due to snapshot injection issues.
        """
        try:
            snap = getattr(payload, "snapshot", None)
            missing = (not isinstance(snap, dict)) or (len(snap) == 0)
            if not missing:
                # Client provided snapshot; do not override.
                md = _ensure_dict(getattr(payload, "metadata", None))
                md.setdefault("snapshot_source", "client")
                payload.metadata = md  # type: ignore[assignment]
                return

            server_snap = KnowledgeSnapshotService.get_snapshot() or {}
            if not isinstance(server_snap, dict):
                server_snap = {}

            payload.snapshot = server_snap  # type: ignore[assignment]

            md = _ensure_dict(getattr(payload, "metadata", None))
            md.setdefault(
                "snapshot_source", "server:KnowledgeSnapshotService.get_snapshot"
            )
            payload.metadata = md  # type: ignore[assignment]
        except Exception:
            # Fail-soft: do not break canonical chat due to snapshot injection issues.
            pass

    def _enforce_output_read_only(out: AgentOutput) -> AgentOutput:
        # Final hard gate (defense-in-depth)
        out.read_only = True

        trace = _ensure_dict(getattr(out, "trace", None))
        trace["endpoint"] = "/api/chat"
        trace["canon"] = "read_propose_only"
        out.trace = trace  # type: ignore[assignment]

        pcs = getattr(out, "proposed_commands", None) or []
        # Normalize to list if something odd came back (fail-soft)
        if isinstance(pcs, dict):
            pcs = []

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

    def _looks_like_orchestrator_route(out: Any) -> bool:
        """
        Detect accidental routing to execution orchestrator or similar non-chat agent.
        This is intentionally heuristic + fail-soft.
        """
        try:
            agent_id = getattr(out, "agent_id", None)
            if (
                isinstance(agent_id, str)
                and agent_id.strip() == "execution_orchestrator"
            ):
                return True

            trace = _ensure_dict(getattr(out, "trace", None))
            selected_agent_id = trace.get("selected_agent_id")
            selected_entrypoint = trace.get("selected_entrypoint")
            if selected_agent_id == "execution_orchestrator":
                return True
            if (
                isinstance(selected_entrypoint, str)
                and "execution_orchestrator" in selected_entrypoint
            ):
                return True

            # If agent failed and router shows orchestrator selection in trace, treat as misroute.
            err = trace.get("error")
            if err and (
                ("ExecutionOrchestrator" in str(err))
                or ("execution_orchestrator" in str(err))
            ):
                return True
        except Exception:
            return False
        return False

    async def _call_ceo_advisor_direct(payload: AgentInput) -> AgentOutput:
        """
        Fallback path: call CEOAdvisorAgent directly to guarantee /api/chat remains chat/propose.
        Uses reflection to avoid assumptions about constructor / method signatures.
        """
        from services.ceo_advisor_agent import CEOAdvisorAgent  # local import

        # 1) If there is an obvious async/sync callable entrypoint, prefer it.
        for method_name in ("run", "chat", "handle", "respond", "invoke"):
            if hasattr(CEOAdvisorAgent, method_name):
                meth = getattr(CEOAdvisorAgent, method_name)
                if callable(meth):
                    try:
                        # Try classmethod/staticmethod style: meth(payload)
                        res = meth(payload)
                        if inspect.isawaitable(res):
                            res = await res
                        if isinstance(res, AgentOutput):
                            return res
                    except TypeError:
                        # Try instance method: CEOAdvisorAgent(...).meth(payload)
                        break
                    except Exception:
                        # We'll try other paths below
                        pass

        # 2) Try to instantiate with best-effort kwargs.
        ctor = CEOAdvisorAgent
        instance = None
        try:
            sig = inspect.signature(ctor)  # type: ignore[arg-type]
            kwargs: Dict[str, Any] = {}
            # Common dependency names used in agent constructors
            for name in sig.parameters.keys():
                if name in ("agent_router", "router", "agent_router_service"):
                    kwargs[name] = agent_router
                elif name in ("snapshot_service", "knowledge_snapshot_service"):
                    kwargs[name] = KnowledgeSnapshotService
            instance = ctor(**kwargs)  # type: ignore[call-arg]
        except Exception:
            # Final attempt: no-arg ctor
            instance = ctor()  # type: ignore[call-arg]

        # 3) Call an instance method
        for method_name in ("run", "chat", "handle", "respond", "invoke"):
            if hasattr(instance, method_name):
                meth = getattr(instance, method_name)
                if callable(meth):
                    res = meth(payload)
                    if inspect.isawaitable(res):
                        res = await res
                    if isinstance(res, AgentOutput):
                        return res

        # 4) Absolute fail-safe: return a typed AgentOutput with error text.
        out = AgentOutput(
            text="CEO Advisor unavailable.",
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={
                "endpoint": "/api/chat",
                "canon": "read_propose_only",
                "error": "CEOAdvisorAgent not callable",
            },
        )
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
        _inject_server_snapshot_if_missing(payload)

        # First attempt: route via AgentRouter (but strongly hinted to CEO Advisor)
        try:
            routed = agent_router.route(payload)
            if inspect.isawaitable(routed):
                routed = await routed  # type: ignore[assignment]
            out = routed  # type: ignore[assignment]
        except Exception as e:
            # Fallback to CEO Advisor directly on router errors
            out = await _call_ceo_advisor_direct(payload)
            out = _enforce_output_read_only(out)
            trace = _ensure_dict(getattr(out, "trace", None))
            trace["router_error"] = repr(e)
            out.trace = trace  # type: ignore[assignment]
            return out

        # If router misrouted to orchestrator, hard fallback to CEO Advisor.
        if _looks_like_orchestrator_route(out):
            out2 = await _call_ceo_advisor_direct(payload)
            out2 = _enforce_output_read_only(out2)
            trace = _ensure_dict(getattr(out2, "trace", None))
            trace["fallback_reason"] = "misrouted_to_execution_orchestrator"
            out2.trace = trace  # type: ignore[assignment]
            return out2

        return _enforce_output_read_only(out)

    return router
