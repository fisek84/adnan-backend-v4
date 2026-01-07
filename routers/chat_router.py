# routers/chat_router.py

from __future__ import annotations

import json
import re
from typing import Any, Dict, Optional, List

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from services.ceo_advisor_agent import create_ceo_advisor_agent
from services.knowledge_snapshot_service import KnowledgeSnapshotService
from services.ops_planner import plan_ai_commands

# Must match gateway_server.PROPOSAL_WRAPPER_INTENT
from models.canon import PROPOSAL_WRAPPER_INTENT

# Commands that are NOT considered "structured/actionable proposals" for fallback detection.
_NON_ACTIONABLE_PROPOSALS = {"refresh_snapshot"}


def build_chat_router(agent_router: Optional[Any] = None) -> APIRouter:
    """
    /api/chat je READ/PROPOSE ONLY.
    - nikad ne izvrĹˇava side-effect
    - injektuje server snapshot ako klijent ne poĹˇalje snapshot
    - CANON: izlazne proposed_commands moraju biti ceo.command.propose wrapper
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

            try:
                wrapper = KnowledgeSnapshotService.get_snapshot() or {}
                if not isinstance(wrapper, dict):
                    wrapper = {}
            except Exception:
                wrapper = {}

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
        Interno drĹľimo List[ProposedCommand] i osiguramo dry_run=True.
        TakoÄ‘er normalizujemo legacy 'params' -> 'args'.
        """
        if raw is None or isinstance(raw, dict):
            return []

        items = raw if isinstance(raw, list) else []
        out: List[ProposedCommand] = []

        for item in items:
            try:
                if hasattr(ProposedCommand, "model_validate"):
                    pc = ProposedCommand.model_validate(item)  # type: ignore[attr-defined]
                else:
                    pc = ProposedCommand.parse_obj(item)  # type: ignore[attr-defined]
            except Exception:
                d = item if isinstance(item, dict) else {}
                args = d.get("args")
                if not isinstance(args, dict) and isinstance(d.get("params"), dict):
                    args = d.get("params") or {}
                if not isinstance(args, dict):
                    args = {}

                cmd = str(d.get("command") or "").strip() or PROPOSAL_WRAPPER_INTENT
                pc = ProposedCommand(command=cmd, args=args)

            try:
                pc.dry_run = True  # type: ignore[assignment]
            except Exception:
                pass

            out.append(pc)

        return out

    def _get_command_name(item: Any) -> str:
        if isinstance(item, ProposedCommand):
            return str(getattr(item, "command", "") or "").strip()
        if isinstance(item, dict):
            return str(item.get("command") or "").strip()
        return ""

    def _has_actionable_proposals(pcs: Any) -> bool:
        if pcs is None or isinstance(pcs, dict):
            return False
        items = pcs if isinstance(pcs, list) else []
        for it in items:
            cmd = _get_command_name(it)
            if not cmd or cmd in _NON_ACTIONABLE_PROPOSALS:
                continue
            return True
        return False

    def _looks_like_goal_or_task_request(prompt: str) -> bool:
        p = (prompt or "").strip().lower()
        if not p:
            return False
        return bool(
            re.search(
                r"\b(goal|cilj|task|zadatak|kreiraj|napravi|create|dodaj|linkaj|pove[zĹľ]i|pove[zĹľ]ite)\b",
                p,
                flags=re.IGNORECASE,
            )
        )

    def _wants_plan_only_json(prompt: str) -> bool:
        p = (prompt or "").strip().lower()
        if not p:
            return False

        wants_json_plan = bool(
            re.search(r"\bisklju[cÄŤ]ivo\b.*\bplan\b.*\bjson\b", p, flags=re.IGNORECASE)
        ) or ("only" in p and "plan" in p and "json" in p)

        forbids_commands = bool(
            re.search(r"\bne\b.*\bkomand", p, flags=re.IGNORECASE)
        ) or bool(re.search(r"\bno\b.*\bcommand", p, flags=re.IGNORECASE))
        forbids_actions = bool(
            re.search(r"\bne\b.*\bakci", p, flags=re.IGNORECASE)
        ) or bool(re.search(r"\bno\b.*\baction", p, flags=re.IGNORECASE))

        return wants_json_plan and (forbids_commands or forbids_actions)

    def _build_proposal_wrapper(prompt: str, *, reason: str) -> ProposedCommand:
        safe_prompt = (prompt or "").strip() or "noop"
        pc = ProposedCommand(
            command=PROPOSAL_WRAPPER_INTENT,
            args={"prompt": safe_prompt},
            reason=reason,
            dry_run=True,
            requires_approval=True,
            risk="LOW",
            scope="api_execute_raw",
            payload_summary={
                "endpoint": "/api/execute/raw",
                "canon": "CEO_CONSOLE_EXECUTION_FLOW",
                "source": "api_chat",
            },
        )
        try:
            if hasattr(pc, "intent"):
                setattr(pc, "intent", PROPOSAL_WRAPPER_INTENT)
        except Exception:
            pass
        return pc

    def _rewrite_any_actionable_to_proposal_wrapper(
        out: AgentOutput, *, prompt: str
    ) -> None:
        """
        CANON:
        /api/chat mora vraÄ‡ati ceo.command.propose (wrapper),
        ÄŤak i ako agent/ops planner interno generiĹˇe notion_write.
        """
        pcs = getattr(out, "proposed_commands", None) or []
        if isinstance(pcs, dict):
            pcs = []
        items = pcs if isinstance(pcs, list) else []

        # Ako veÄ‡ postoji wrapper, ostavi ga (ali osiguraj args.prompt postoji).
        for it in items:
            if _get_command_name(it) == PROPOSAL_WRAPPER_INTENT:
                # Ensure args.prompt present (legacy might be params)
                try:
                    if isinstance(it, ProposedCommand):
                        if not isinstance(getattr(it, "args", None), dict):
                            it.args = {}  # type: ignore[assignment]
                        if "prompt" not in it.args:
                            it.args["prompt"] = (prompt or "").strip() or "noop"
                except Exception:
                    pass
                return

        # Ako imamo actionable komande (npr notion_write), rewrite u wrapper.
        if _has_actionable_proposals(items):
            tr = _ensure_dict(getattr(out, "trace", None))
            tr["rewrote_proposed_commands_to_ceo_command_propose"] = True
            tr["rewrote_from"] = items
            tr["router_version"] = "chat-canon-wrapper-rewrite-v1"
            out.trace = tr  # type: ignore[assignment]

            out.proposed_commands = [
                _build_proposal_wrapper(
                    prompt, reason="Canonical chat proposal wrapper (rewrite)."
                )
            ]  # type: ignore[assignment]
            return

        # Ako nema niĹˇta actionable (prazno ili samo refresh_snapshot), ubaci fallback wrapper.
        out.proposed_commands = [
            _build_proposal_wrapper(
                prompt, reason="Fallback proposal (no actionable proposals)."
            )
        ]  # type: ignore[assignment]
        tr = _ensure_dict(getattr(out, "trace", None))
        tr["fallback_proposed_commands"] = True
        tr["router_version"] = "chat-canon-wrapper-rewrite-v1"
        out.trace = tr  # type: ignore[assignment]

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

    async def _try_attach_ops_plan_trace(
        out: AgentOutput, *, prompt: str, snapshot: Any
    ) -> None:
        """
        Ops planner koristimo da bismo dobili strukturirani plan u trace,
        ali NE smijemo ga vratiti kao actionable notion_write iz /api/chat.
        """
        if not _looks_like_goal_or_task_request(prompt):
            return
        try:
            plan = await plan_ai_commands(
                prompt, snapshot if snapshot is not None else {}
            )
        except Exception:
            plan = None

        tr = _ensure_dict(getattr(out, "trace", None))
        tr["ops_plan_attempted"] = True
        tr["ops_plan_source"] = "services.ops_planner.plan_ai_commands"

        if isinstance(plan, dict) and "goal" in plan and "task" in plan:
            tr["ops_plan"] = plan
            tr["ops_plan_attached"] = True
        else:
            tr["ops_plan_attached"] = False

        out.trace = tr  # type: ignore[assignment]

    async def _enforce_plan_only_json_response(
        out: AgentOutput, *, prompt: str, snapshot: Any
    ) -> None:
        """
        Hard gate: korisnik traĹľi iskljuÄŤivo plan u JSON i zabranjuje komande.
        """
        try:
            plan = await plan_ai_commands(
                prompt, snapshot if snapshot is not None else {}
            )
        except Exception:
            plan = None

        if not isinstance(plan, dict) or "goal" not in plan or "task" not in plan:
            out.text = json.dumps({"error": "plan_unavailable"}, ensure_ascii=False)
            out.proposed_commands = []  # type: ignore[assignment]
            tr = _ensure_dict(getattr(out, "trace", None))
            tr["plan_only_requested"] = True
            tr["plan_only_enforced"] = False
            out.trace = tr  # type: ignore[assignment]
            return

        out.text = json.dumps(plan, ensure_ascii=False, indent=2)
        out.proposed_commands = []  # type: ignore[assignment]
        tr = _ensure_dict(getattr(out, "trace", None))
        tr["plan_only_requested"] = True
        tr["plan_only_enforced"] = True
        tr["mode"] = "plan_only"
        tr["ops_plan"] = plan
        tr["ops_plan_attached"] = True
        tr["ops_plan_source"] = "services.ops_planner.plan_ai_commands"
        tr["router_version"] = "chat-plan-only-json-enforced-v1"
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

    def _agent_output_to_dict_no_alias(out: AgentOutput) -> Dict[str, Any]:
        """
        Force by_alias=False so we always emit 'args' (not 'params').
        """
        try:
            if hasattr(out, "model_dump"):
                d = out.model_dump(by_alias=False)  # type: ignore[attr-defined]
                return d if isinstance(d, dict) else {}
        except Exception:
            pass

        try:
            if hasattr(out, "dict"):
                d = out.dict(by_alias=False)  # type: ignore[attr-defined]
                return d if isinstance(d, dict) else {}
        except Exception:
            pass

        return {
            "text": getattr(out, "text", ""),
            "proposed_commands": getattr(out, "proposed_commands", []) or [],
            "agent_id": getattr(out, "agent_id", None),
            "read_only": True,
            "trace": getattr(out, "trace", {}) or {},
        }

    @router.post("/chat", response_model=AgentOutput, response_model_by_alias=False)
    async def chat(payload: AgentInput):
        _enforce_input_read_only(payload)
        _inject_server_snapshot_if_missing(payload)

        out = await _call_agent(payload)
        prompt = _extract_prompt(payload)
        snapshot = getattr(payload, "snapshot", None)

        # PLAN ONLY JSON (hard gate)
        if _wants_plan_only_json(prompt):
            await _enforce_plan_only_json_response(
                out, prompt=prompt, snapshot=snapshot
            )
            out = _enforce_output_read_only(out, payload)
            return JSONResponse(content=_agent_output_to_dict_no_alias(out))

        # Attach ops plan to trace when it makes sense (for debug/observability)
        await _try_attach_ops_plan_trace(out, prompt=prompt, snapshot=snapshot)

        # CANON: rewrite output proposals to ceo.command.propose wrapper
        _rewrite_any_actionable_to_proposal_wrapper(out, prompt=prompt)

        out = _enforce_output_read_only(out, payload)
        return JSONResponse(content=_agent_output_to_dict_no_alias(out))

    return router
