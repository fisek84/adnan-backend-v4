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
                    command=str(d.get("command") or ""),
                    args=args if isinstance(args, dict) else {},
                )

            # /api/chat je uvijek read-only: dry_run mora biti True
            try:
                pc.dry_run = True
            except Exception:
                pass

            out.append(pc)

        return out

    def _looks_like_write_intent(text: str) -> bool:
        t = (text or "").strip().lower()
        if not t:
            return False
        return any(
            k in t
            for k in [
                "create",
                "kreiraj",
                "napravi",
                "dodaj",
                "update",
                "azuriraj",
                "izmijeni",
                "promijeni",
                "delete",
                "obrisi",
                "ukloni",
                "task",
                "zadatak",
                "goal",
                "cilj",
                "notion",
                "db:",
                "database",
            ]
        )

    def _build_approval_wrapper(prompt: str, *, reason: str) -> ProposedCommand:
        """
        Wrapper koji se šalje na /api/execute/raw (gateway će unwrap+translate i kreirati approval).
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
        return pc

    def _build_contract_noop_wrapper(prompt: str) -> ProposedCommand:
        """
        NOOP wrapper: stabilizira contract, ali nije executable.
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
                # NOTE: do NOT rely on this being complete; we hard-normalize below anyway.
            },
        )
        return pc

    def _pc_to_dict(pc: ProposedCommand, *, prompt: str) -> Dict[str, Any]:
        d = (
            pc.model_dump(by_alias=False)
            if hasattr(pc, "model_dump")
            else pc.dict(by_alias=False)
        )
        if not isinstance(d, dict):
            return {}

        # osiguraj args dict + args.prompt za wrapper
        args = d.get("args")
        if not isinstance(args, dict):
            args = {}
            d["args"] = args

        p = args.get("prompt")
        if not isinstance(p, str) or not p.strip():
            args["prompt"] = (prompt or "").strip() or "noop"

        return d

    def _ensure_payload_summary_contract(pc_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        HARD CONTRACT (SSOT):
        Every proposed_command returned from /api/chat MUST include payload_summary fields:
          - confidence_score: float [0.0, 1.0]
          - assumption_count: int >= 0
          - recommendation_type: enum string (at least INFORMATIONAL/OPERATIONAL)
        This prevents "new problems" across fallback paths.
        """
        if not isinstance(pc_dict, dict):
            return {}

        ps = pc_dict.get("payload_summary")
        if not isinstance(ps, dict):
            ps = {}
            pc_dict["payload_summary"] = ps

        kind = ps.get("kind")
        is_noop = kind == "contract_noop"

        # confidence_score: float in [0,1]
        cs = ps.get("confidence_score")
        if not isinstance(cs, (int, float)):
            cs = 1.0 if is_noop else 0.5
        csf = float(cs)
        if csf < 0.0:
            csf = 0.0
        if csf > 1.0:
            csf = 1.0
        ps["confidence_score"] = csf

        # assumption_count: int >= 0
        ac = ps.get("assumption_count")
        if not isinstance(ac, int) or ac < 0:
            ac = 0
        ps["assumption_count"] = ac

        # recommendation_type: required
        rt = ps.get("recommendation_type")
        if not isinstance(rt, str) or not rt.strip():
            ps["recommendation_type"] = "INFORMATIONAL" if is_noop else "OPERATIONAL"

        return pc_dict

    def _is_actionable(pc: ProposedCommand) -> bool:
        """
        Actionable = nije wrapper i nije u NON_ACTIONABLE setu.
        (tj. stvarna komanda: create_page, notion.query, itd.)
        """
        cmd = getattr(pc, "command", None)
        if not isinstance(cmd, str) or not cmd.strip():
            return False

        if cmd == PROPOSAL_WRAPPER_INTENT:
            return False

        if cmd in _NON_ACTIONABLE_PROPOSALS:
            return False

        return True

    def _finalize_actionable(pc: ProposedCommand) -> None:
        """
        /api/chat: dry_run True, ali "requires_approval" treba biti True da UI zna da ide approval tok.
        """
        try:
            pc.dry_run = True
        except Exception:
            pass

        try:
            if getattr(pc, "requires_approval", None) is not True:
                pc.requires_approval = True
        except Exception:
            pass

        try:
            scope = getattr(pc, "scope", None)
            if not isinstance(scope, str) or not scope.strip():
                pc.scope = "api_execute_raw"
        except Exception:
            pass

        try:
            risk = getattr(pc, "risk", None)
            if not isinstance(risk, str) or not risk.strip():
                pc.risk = "LOW"
        except Exception:
            pass

    @router.post("/chat", response_model=AgentOutput, response_model_by_alias=False)
    async def chat(payload: AgentInput):
        mem_ro = get_memory_read_only_service()
        mem_snapshot = mem_ro.export_public_snapshot() if mem_ro else {}

        out = await create_ceo_advisor_agent(payload, {"memory": mem_snapshot})
        prompt = _extract_prompt(payload)

        pcs = getattr(out, "proposed_commands", None)
        normalized = _normalize_proposed_commands(pcs)

        actionable = [pc for pc in normalized if _is_actionable(pc)]

        # ✅ KLJUČNA PROMJENA:
        # Ako imamo stvarne actionable komande, VRATI IH (ne wrapaj).
        if actionable:
            for pc in actionable:
                _finalize_actionable(pc)

            # Hard-normalize payload_summary contract in dict output (safe across model versions)
            pcs_out: List[Dict[str, Any]] = []
            for pc in actionable:
                d = (
                    pc.model_dump(by_alias=False)
                    if hasattr(pc, "model_dump")
                    else pc.dict(by_alias=False)
                )
                if isinstance(d, dict):
                    pcs_out.append(_ensure_payload_summary_contract(d))

            return JSONResponse(
                content={
                    "text": out.text,
                    "proposed_commands": pcs_out,
                    "agent_id": out.agent_id,
                    "read_only": True,
                    "trace": out.trace or {},
                }
            )

        # Nema actionable komandi → fallback:
        # - ako je write intent → vrati approval wrapper (da gateway može translate na /execute/raw)
        # - ako nije write → noop wrapper
        if _looks_like_write_intent(prompt):
            fallback = _build_approval_wrapper(
                prompt,
                reason="Approval required (write intent, but no structured proposal returned).",
            )
        else:
            fallback = _build_contract_noop_wrapper(prompt)

        out.read_only = True

        fb = _pc_to_dict(fallback, prompt=prompt)
        fb = _ensure_payload_summary_contract(fb)

        return JSONResponse(
            content={
                "text": out.text,
                "proposed_commands": [fb],
                "agent_id": out.agent_id,
                "read_only": True,
                "trace": out.trace or {},
            }
        )

    return router
