# routers/chat_router.py

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from services.ceo_advisor_agent import create_ceo_advisor_agent
from dependencies import get_memory_read_only_service

# Must match gateway_server.PROPOSAL_WRAPPER_INTENT
from models.canon import PROPOSAL_WRAPPER_INTENT

# Commands that are NOT considered "structured/actionable proposals" for fallback detection.
_NON_ACTIONABLE_PROPOSALS = {"refresh_snapshot"}


def build_chat_router(agent_router: Optional[Any] = None) -> APIRouter:
    router = APIRouter()

    def _extract_prompt(payload: AgentInput) -> str:
        for k in ("message", "text", "input_text", "prompt"):
            v = getattr(payload, k, None)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def _normalize_proposed_commands(raw: Any) -> List[ProposedCommand]:
        if raw is None:
            return []

        items = [raw] if isinstance(raw, dict) else raw if isinstance(raw, list) else []
        out: List[ProposedCommand] = []

        for item in items:
            try:
                pc = (
                    ProposedCommand.model_validate(item)
                    if hasattr(ProposedCommand, "model_validate")
                    else ProposedCommand.parse_obj(item)
                )
            except Exception:
                d = item if isinstance(item, dict) else {}
                args = d.get("args") or d.get("params") or {}
                pc = ProposedCommand(
                    command=str(d.get("command") or PROPOSAL_WRAPPER_INTENT),
                    args=args if isinstance(args, dict) else {},
                )

            # Ensure chat is read-only: proposals are always dry_run here.
            try:
                pc.dry_run = True
            except Exception:
                pass

            out.append(pc)

        return out

    def _build_approval_wrapper(prompt: str, *, reason: str) -> ProposedCommand:
        """
        Enterprise/canon: use when we have an actionable proposal that must go through approval.
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
                "confidence_score": 0.5,
                "assumption_count": 0,
                "recommendation_type": "OPERATIONAL",
            },
        )

        # Defensive: ensure we do not persist intent on wrapper if the model sets it.
        try:
            if hasattr(pc, "intent"):
                pc.intent = None
        except Exception:
            pass

        return pc

    def _build_contract_noop_wrapper(prompt: str) -> ProposedCommand:
        """
        Contract stability wrapper:
          - satisfies proposed_commands[0].args.prompt
          - MUST NOT be actionable (no approval, no execute scope)
        """
        safe_prompt = (prompt or "").strip() or "noop"

        pc = ProposedCommand(
            command=PROPOSAL_WRAPPER_INTENT,
            args={"prompt": safe_prompt},
            reason="Contract stability no-op (read-only chat produced no actionable proposals).",
            dry_run=True,
            requires_approval=False,
            risk="NONE",
            scope="none",
            payload_summary={
                "canon": "CEO_CONSOLE_EXECUTION_FLOW",
                "source": "api_chat",
                "kind": "contract_noop",
            },
        )

        try:
            if hasattr(pc, "intent"):
                pc.intent = None
        except Exception:
            pass

        return pc

    def _pc_to_dict(pc: ProposedCommand, *, prompt: str) -> Dict[str, Any]:
        d = (
            pc.model_dump(by_alias=False)
            if hasattr(pc, "model_dump")
            else pc.dict(by_alias=False)
        )
        if not isinstance(d, dict):
            return {}

        # Contract enforcement: proposed_commands[0].args.prompt MUST exist.
        # Also normalize possible "params" -> "args" if present.
        if "args" not in d and "params" in d:
            params = d.get("params")
            d["args"] = params if isinstance(params, dict) else {}
            try:
                del d["params"]
            except Exception:
                pass

        args = d.get("args")
        if not isinstance(args, dict):
            args = {}
            d["args"] = args

        p = args.get("prompt")
        if not isinstance(p, str) or not p.strip():
            args["prompt"] = (prompt or "").strip() or "noop"

        return d

    def _is_actionable(pc: ProposedCommand) -> bool:
        """
        Minimal actionable heuristic:
          - anything not in NON_ACTIONABLE, and not the wrapper itself.
        """
        try:
            cmd = getattr(pc, "command", None)
        except Exception:
            cmd = None

        if not isinstance(cmd, str) or not cmd.strip():
            return False

        if cmd == PROPOSAL_WRAPPER_INTENT:
            return False

        if cmd in _NON_ACTIONABLE_PROPOSALS:
            return False

        return True

    @router.post("/chat", response_model=AgentOutput, response_model_by_alias=False)
    async def chat(payload: AgentInput):
        mem_ro = get_memory_read_only_service()
        mem_snapshot = mem_ro.export_public_snapshot() if mem_ro else {}
        out = await create_ceo_advisor_agent(payload, {"memory": mem_snapshot})
        prompt = _extract_prompt(payload)

        pcs = getattr(out, "proposed_commands", None)
        out.proposed_commands = _normalize_proposed_commands(pcs)

        # Enterprise behavior:
        # - if actionable commands appear, wrap into approval-required wrapper
        # - else return contract-stability no-op wrapper (non-actionable)
        if any(_is_actionable(pc) for pc in out.proposed_commands):
            out.proposed_commands = [
                _build_approval_wrapper(
                    prompt,
                    reason="Approval required (actionable intent detected).",
                )
            ]
        else:
            out.proposed_commands = [_build_contract_noop_wrapper(prompt)]

        out.read_only = True

        return JSONResponse(
            content={
                "text": out.text,
                "proposed_commands": [
                    _pc_to_dict(pc, prompt=prompt) for pc in out.proposed_commands
                ],
                "agent_id": out.agent_id,
                "read_only": True,
                "trace": out.trace or {},
            }
        )

    return router
