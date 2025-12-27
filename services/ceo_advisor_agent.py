# services/ceo_advisor_agent.py
from __future__ import annotations

from typing import Any, Dict, List

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from services.agent_router.openai_assistant_executor import OpenAIAssistantExecutor


def _to_proposed_commands(items: Any) -> List[ProposedCommand]:
    if not isinstance(items, list):
        return []
    out: List[ProposedCommand] = []
    for x in items:
        if not isinstance(x, dict):
            continue
        cmd = str(x.get("command") or x.get("command_type") or "").strip()
        args = x.get("args") or x.get("payload") or {}
        if not cmd:
            continue
        if not isinstance(args, dict):
            args = {}
        out.append(
            ProposedCommand(
                command=cmd,
                args=args,
                reason=str(x.get("reason") or "proposed by ceo_advisor").strip(),
                requires_approval=bool(x.get("requires_approval", True)),
                risk=str(x.get("risk") or x.get("risk_hint") or "").strip() or "MEDIUM",
                dry_run=True,
            )
        )
    return out


def _pick_text(result: Any) -> str:
    """
    Prefer summary/text fields; fallback to string.
    """
    if isinstance(result, dict):
        for k in ("text", "summary", "assistant_text", "message", "output_text", "response"):
            v = result.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        raw = result.get("raw")
        if isinstance(raw, dict):
            for k in ("text", "summary", "assistant_text", "message", "output_text", "response"):
                v = raw.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    if isinstance(result, str) and result.strip():
        return result.strip()
    return ""


def _format_enforcer(user_text: str) -> str:
    """
    Hard requirement: output must list concrete items.
    This is injected into the prompt so the assistant doesn't reply with vague prose.
    """
    return (
        f"{user_text.strip()}\n\n"
        "OBAVEZAN FORMAT ODGOVORA (ne preskakati):\n"
        "GOALS (top 3)\n"
        "1) <name> | <status> | <priority>\n"
        "2) <name> | <status> | <priority>\n"
        "3) <name> | <status> | <priority>\n\n"
        "TASKS (top 5)\n"
        "1) <title> | <status> | <priority>\n"
        "2) <title> | <status> | <priority>\n"
        "3) <title> | <status> | <priority>\n"
        "4) <title> | <status> | <priority>\n"
        "5) <title> | <status> | <priority>\n\n"
        "PRAVILA:\n"
        "- Koristi isključivo podatke iz snapshot-a.\n"
        "- Ako nema dovoljno (3 cilja ili 5 taskova), ispiši koliko postoji i dodaj liniju: "
        "\"NEMA DOVOLJNO PODATAKA U SNAPSHOT-U\".\n"
        "- Ne piši opšti opis bez liste stavki.\n"
    )


async def create_ceo_advisor_agent(agent_input: AgentInput, ctx: Dict[str, Any]) -> AgentOutput:
    """
    ENTRYPOINT za AgentRouterService.
    Mora potpis: (AgentInput, ctx) -> AgentOutput (sync ili async).
    """
    base_text = (agent_input.message or "").strip()
    if not base_text:
        base_text = "Vrati stanje iz snapshot-a po kanonskom formatu."

    snapshot = agent_input.snapshot if isinstance(agent_input.snapshot, dict) else {}

    # Canon read-only
    safe_context: Dict[str, Any] = {
        "canon": {"read_only": True, "no_tools": True, "no_side_effects": True},
        "snapshot": snapshot,
        "metadata": agent_input.metadata if isinstance(agent_input.metadata, dict) else {},
    }

    # Inject strict output format into prompt
    enforced_text = _format_enforcer(base_text)

    executor = OpenAIAssistantExecutor()
    result = await executor.ceo_command(text=enforced_text, context=safe_context)

    text_out = _pick_text(result)
    if not text_out:
        text_out = "CEO advisor nije vratio tekstualni output."

    # Proposed commands: be tolerant to naming
    proposed_items = None
    if isinstance(result, dict):
        proposed_items = result.get("proposed_commands")
        if proposed_items is None:
            proposed_items = result.get("proposed_commands")
        if proposed_items is None:
            proposed_items = result.get("proposed_commands")

    proposed = _to_proposed_commands(proposed_items)

    trace = ctx.get("trace") if isinstance(ctx, dict) else {}
    if not isinstance(trace, dict):
        trace = {}

    # Required trace signals
    trace["agent_output_text_len"] = len(text_out)
    trace["agent_router_empty_text"] = (len(text_out) == 0)

    # Return both summary + text if your AgentOutput model supports it:
    # - If AgentOutput does not have "summary", keep it in text only.
    return AgentOutput(
        text=text_out,
        proposed_commands=proposed,
        agent_id="ceo_advisor",
        read_only=True,
        trace=trace,
    )
