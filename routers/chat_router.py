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
    - nikad ne izvršava side-effect
    - injektuje server snapshot ako klijent ne pošalje snapshot

    CANON (NATURAL CHAT):
      - /api/chat mora vratiti proposed_commands=[] za non-write upite
      - wrapper (ceo.command.propose) se vraća samo kad:
          a) klijent eksplicitno traži require_approval=True, ili
          b) agent vrati actionable proposal-e (npr. notion_write), ili
          c) heuristika detektuje write intent u promptu
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
        """
        READ ONLY:
          - uvijek read_only=True
          - require_approval: NE FORCE-amo na True (default mora biti natural chat)
            -> čitamo eventualno postojeću vrijednost iz payload.metadata.require_approval
        """
        md = _ensure_dict(getattr(payload, "metadata", None))

        # Preserve/derive require_approval (default False)
        req_appr = md.get("require_approval")
        require_approval = bool(req_appr) if isinstance(req_appr, (bool, int)) else False

        md["read_only"] = True
        md["require_approval"] = require_approval
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
        Interno držimo List[ProposedCommand] i osiguramo dry_run=True.
        Također normalizujemo legacy 'params' -> 'args'.
        """
        if raw is None:
            return []

        # If a single dict sneaks in, normalize to list.
        if isinstance(raw, dict):
            items = [raw]
        else:
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
                r"\b(goal|cilj|task|zadatak|kreiraj|napravi|create|dodaj|linkaj|pove[zž]i|pove[zž]ite)\b",
                p,
                flags=re.IGNORECASE,
            )
        )

    def _looks_like_write_intent(prompt: str) -> bool:
        """
        Minimal deterministic write-intent detection for natural chat.
        (Same spirit as gateway _inject_fallback_proposed_commands.)
        """
        p = (prompt or "").strip().lower()
        if not p:
            return False

        return any(
            k in p
            for k in [
                "create",
                "kreiraj",
                "napravi",
                "dodaj",
                "update",
                "azuriraj",
                "ažuriraj",
                "izmijeni",
                "promijeni",
                "delete",
                "obrisi",
                "obriši",
                "ukloni",
                "task",
                "zadatak",
                "goal",
                "cilj",
                "notion",
            ]
        )

    def _wants_plan_only_json(prompt: str) -> bool:
        p = (prompt or "").strip().lower()
        if not p:
            return False

        wants_json_plan = bool(
            re.search(r"\bisklju[cč]ivo\b.*\bplan\b.*\bjson\b", p, flags=re.IGNORECASE)
        ) or ("only" in p and "plan" in p and "json" in p)

        forbids_commands = bool(
            re.search(r"\bne\b.*\bkomand", p, flags=re.IGNORECASE)
        ) or bool(re.search(r"\bno\b.*\bcommand", p, flags=re.IGNORECASE))
        forbids_actions = bool(
            re.search(r"\bne\b.*\bakci", p, flags=re.IGNORECASE)
        ) or bool(re.search(r"\bno\b.*\baction", p, flags=re.IGNORECASE))

        return wants_json_plan and (forbids_commands or forbids_actions)

    def _build_proposal_wrapper(prompt: str, *, reason: str) -> ProposedCommand:
        """
        Canonical /api/chat proposal wrapper.
        IMPORTANT: args.prompt MUST exist for contract stability when wrapper is returned.
        """
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
        # Do not force intent here; gateway unwrap uses command==PROPOSAL_WRAPPER_INTENT.
        try:
            if hasattr(pc, "intent"):
                setattr(pc, "intent", None)
        except Exception:
            pass
        return pc

    def _proposal_wrapper_dict(prompt: str, *, reason: str) -> Dict[str, Any]:
        safe_prompt = (prompt or "").strip() or "noop"
        return {
            "command": PROPOSAL_WRAPPER_INTENT,
            "args": {"prompt": safe_prompt},
            "intent": None,
            "reason": reason,
            "dry_run": True,
            "requires_approval": True,
            "risk": "LOW",
            "scope": "api_execute_raw",
            "payload_summary": {
                "endpoint": "/api/execute/raw",
                "canon": "CEO_CONSOLE_EXECUTION_FLOW",
                "source": "api_chat",
            },
        }

    def _ensure_wrapper_shape_on_first(result: Dict[str, Any], *, prompt: str) -> None:
        """
        If proposed_commands already contains wrapper, enforce args.prompt non-empty on it.
        Does NOT inject wrapper when list is empty (natural chat).
        """
        if not isinstance(result, dict):
            return

        pcs_any = result.get("proposed_commands")
        pcs_list: List[Any] = pcs_any if isinstance(pcs_any, list) else []

        if not pcs_list:
            # Natural chat => keep empty
            result["proposed_commands"] = []
            return

        # Normalize all items to dict and params->args
        normalized: List[Dict[str, Any]] = []
        for it in pcs_list:
            d: Dict[str, Any]
            if isinstance(it, dict):
                d = dict(it)
            elif hasattr(it, "model_dump"):
                try:
                    md = it.model_dump(by_alias=False)  # type: ignore[attr-defined]
                    d = dict(md) if isinstance(md, dict) else {}
                except Exception:
                    d = {}
            elif hasattr(it, "dict"):
                try:
                    md = it.dict(by_alias=False)  # type: ignore[attr-defined]
                    d = dict(md) if isinstance(md, dict) else {}
                except Exception:
                    d = {}
            else:
                d = {}

            if not d:
                continue

            args = d.get("args")
            if not isinstance(args, dict):
                args = {}
            if "prompt" not in args:
                params = d.get("params")
                if isinstance(params, dict):
                    p0 = params.get("prompt")
                    if isinstance(p0, str) and p0.strip():
                        args["prompt"] = p0.strip()
            d["args"] = args
            normalized.append(d)

        if not normalized:
            result["proposed_commands"] = []
            return

        # If first is wrapper, enforce args.prompt. If not wrapper, leave as-is.
        first = normalized[0]
        cmd = first.get("command")
        intent = first.get("intent")
        is_wrapper = (cmd == PROPOSAL_WRAPPER_INTENT) or (intent == PROPOSAL_WRAPPER_INTENT)

        if is_wrapper:
            a2 = first.get("args")
            if not isinstance(a2, dict):
                a2 = {}
            p2 = a2.get("prompt")
            if not isinstance(p2, str) or not p2.strip():
                a2["prompt"] = (prompt or "").strip() or "noop"
            first["args"] = a2
            first["command"] = PROPOSAL_WRAPPER_INTENT
            first["intent"] = None
            normalized[0] = first

            tr = result.get("trace")
            if not isinstance(tr, dict):
                tr = {}
            tr["canon_chat_contract"] = "wrapper.args.prompt"
            result["trace"] = tr

        result["proposed_commands"] = normalized

    # -----------------------------
    # OPS PLAN -> attach to trace (READ/PROPOSE ONLY)
    # -----------------------------

    def _is_valid_ops_plan(plan: Any) -> bool:
        return (
            isinstance(plan, dict)
            and isinstance(plan.get("goal"), dict)
            and isinstance(plan.get("task"), dict)
        )

    async def _rewrite_any_actionable_to_proposal_wrapper(
        out: AgentOutput, *, prompt: str, snapshot: Any, require_approval: bool
    ) -> None:
        """
        NATURAL CHAT:
          - wrapper se vraća samo kad treba (write intent / require_approval / actionable agent output)
          - inače proposed_commands ostaje []
        """
        pcs = getattr(out, "proposed_commands", None) or []
        if isinstance(pcs, dict):
            pcs = []
        items = pcs if isinstance(pcs, list) else []

        is_goal_task = _looks_like_goal_or_task_request(prompt)
        write_like = _looks_like_write_intent(prompt)

        # If goal/task request, we may attach plan to trace, but we do NOT force wrapper unless approval/write is desired.
        if is_goal_task:
            plan = None
            try:
                plan = await plan_ai_commands(
                    prompt, snapshot if snapshot is not None else {}
                )
            except Exception:
                plan = None

            tr = _ensure_dict(getattr(out, "trace", None))
            tr["ops_plan_attempted"] = True
            tr["ops_plan_source"] = "services.ops_planner.plan_ai_commands"
            tr["router_version"] = "chat-ops-plan-trace-only-v3"

            if _is_valid_ops_plan(plan):
                tr["ops_plan_attached"] = True
                tr["ops_plan"] = plan
            else:
                tr["ops_plan_attached"] = False

            out.trace = tr  # type: ignore[assignment]
            # fallthrough (decision about wrapper below)

        # If wrapper already exists, normalize it to be single-item and ensure args.prompt.
        for it in items:
            if _get_command_name(it) == PROPOSAL_WRAPPER_INTENT:
                if isinstance(it, ProposedCommand):
                    try:
                        if not isinstance(getattr(it, "args", None), dict):
                            it.args = {}  # type: ignore[assignment]
                        if (
                            "prompt" not in it.args
                            or not str(it.args.get("prompt") or "").strip()
                        ):
                            it.args["prompt"] = (prompt or "").strip() or "noop"
                    except Exception:
                        pass
                    out.proposed_commands = [it]  # type: ignore[assignment]
                elif isinstance(it, dict):
                    d = dict(it)
                    args = d.get("args")
                    if not isinstance(args, dict):
                        args = {}
                    if (
                        "prompt" not in args
                        or not str(args.get("prompt") or "").strip()
                    ):
                        params = d.get("params")
                        if (
                            isinstance(params, dict)
                            and isinstance(params.get("prompt"), str)
                            and params["prompt"].strip()
                        ):
                            args["prompt"] = params["prompt"].strip()
                        else:
                            args["prompt"] = (prompt or "").strip() or "noop"
                    d["args"] = args
                    d["command"] = PROPOSAL_WRAPPER_INTENT
                    d["intent"] = None
                    out.proposed_commands = [d]  # type: ignore[assignment]
                else:
                    out.proposed_commands = [
                        _build_proposal_wrapper(
                            prompt,
                            reason="Canonical chat proposal wrapper (normalize existing).",
                        )
                    ]  # type: ignore[assignment]
                return

        actionable_from_agent = _has_actionable_proposals(items)

        # Only return wrapper when we actually want approval path.
        if require_approval or write_like or actionable_from_agent:
            tr = _ensure_dict(getattr(out, "trace", None))
            tr["router_version"] = "chat-wrapper-conditional-v1"
            tr["require_approval"] = require_approval
            tr["write_like"] = write_like
            tr["actionable_from_agent"] = actionable_from_agent

            if actionable_from_agent:
                tr["rewrote_proposed_commands_to_ceo_command_propose"] = True
                tr["rewrote_from"] = items

            out.trace = tr  # type: ignore[assignment]

            out.proposed_commands = [
                _build_proposal_wrapper(
                    prompt,
                    reason="Approval required (write/approval intent detected). Promote via ceo.command.propose.",
                )
            ]  # type: ignore[assignment]
            return

        # Natural chat: no proposals
        out.proposed_commands = []  # type: ignore[assignment]
        tr = _ensure_dict(getattr(out, "trace", None))
        tr["router_version"] = "chat-natural-no-proposals-v1"
        tr["require_approval"] = require_approval
        tr["write_like"] = write_like
        tr["actionable_from_agent"] = actionable_from_agent
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

    async def _enforce_plan_only_json_response(
        out: AgentOutput, *, prompt: str, snapshot: Any
    ) -> None:
        """
        Hard gate: korisnik traži isključivo plan u JSON i zabranjuje komande.

        NOTE:
          - This function sets proposed_commands=[]. (i ostaje prazno)
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
        trace["require_approval"] = md.get("require_approval", False)
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

        md = _ensure_dict(getattr(payload, "metadata", None))
        require_approval = bool(md.get("require_approval") or False)

        # PLAN ONLY JSON (hard gate)
        if _wants_plan_only_json(prompt):
            await _enforce_plan_only_json_response(
                out, prompt=prompt, snapshot=snapshot
            )
            out = _enforce_output_read_only(out, payload)
            result = _agent_output_to_dict_no_alias(out)

            # Natural chat: keep proposed_commands=[]
            if not isinstance(result.get("proposed_commands"), list):
                result["proposed_commands"] = []
            return JSONResponse(content=result)

        # Conditional wrapper (only when needed)
        await _rewrite_any_actionable_to_proposal_wrapper(
            out, prompt=prompt, snapshot=snapshot, require_approval=require_approval
        )

        out = _enforce_output_read_only(out, payload)
        result = _agent_output_to_dict_no_alias(out)

        # Ensure proposed_commands is a list; if wrapper is present, enforce args.prompt.
        if not isinstance(result.get("proposed_commands"), list):
            result["proposed_commands"] = []
        _ensure_wrapper_shape_on_first(result, prompt=prompt)

        return JSONResponse(content=result)

    return router
