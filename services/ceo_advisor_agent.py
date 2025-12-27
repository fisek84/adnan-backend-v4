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
    if isinstance(result, dict):
        for k in (
            "text",
            "summary",
            "assistant_text",
            "message",
            "output_text",
            "response",
        ):
            v = result.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        raw = result.get("raw")
        if isinstance(raw, dict):
            for k in (
                "text",
                "summary",
                "assistant_text",
                "message",
                "output_text",
                "response",
            ):
                v = raw.get(k)
                if isinstance(v, str) and v.strip():
                    return v.strip()
        if isinstance(raw, str) and raw.strip():
            return raw.strip()
    if isinstance(result, str) and result.strip():
        return result.strip()
    return ""


def _format_enforcer(user_text: str) -> str:
    return (
        f"{user_text.strip()}\n\n"
        "OBAVEZAN FORMAT ODGOVORA:\n"
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
        "- Koristi ISKLJUČIVO podatke iz snapshot-a.\n"
        "- Ako nema dovoljno podataka, napiši: NEMA DOVOLJNO PODATAKA U SNAPSHOT-U.\n"
    )


async def create_ceo_advisor_agent(
    agent_input: AgentInput, ctx: Dict[str, Any]
) -> AgentOutput:
    base_text = (agent_input.message or "").strip()
    if not base_text:
        base_text = "Vrati stanje iz snapshot-a po kanonskom formatu."

    snapshot = agent_input.snapshot if isinstance(agent_input.snapshot, dict) else {}

    # =========================================================
    # 🔴 SNAPSHOT GUARD — AKO JE PRAZAN, NE ZOVI LLM
    # =========================================================
    dashboard = snapshot.get("dashboard") if isinstance(snapshot, dict) else {}
    goals = dashboard.get("goals") if isinstance(dashboard, dict) else None
    tasks = dashboard.get("tasks") if isinstance(dashboard, dict) else None

    if not goals and not tasks:
        return AgentOutput(
            text=(
                "NEMA DOVOLJNO PODATAKA U SNAPSHOT-U.\n\n"
                "Snapshot je prazan ili ne sadrži ciljeve i taskove."
            ),
            proposed_commands=[
                ProposedCommand(
                    command="refresh_snapshot",
                    args={"source": "ceo_dashboard"},
                    reason="Snapshot je prazan ili nedostaje.",
                    requires_approval=True,
                    risk="LOW",
                    dry_run=True,
                )
            ],
            agent_id="ceo_advisor",
            read_only=True,
            trace={
                "snapshot_empty": True,
                "snapshot_source": snapshot.get("source"),
            },
        )

    # =========================================================
    # NORMALAN LLM PUT
    # =========================================================
    safe_context: Dict[str, Any] = {
        "canon": {"read_only": True, "no_tools": True, "no_side_effects": True},
        "snapshot": snapshot,
        "metadata": agent_input.metadata
        if isinstance(agent_input.metadata, dict)
        else {},
    }

    enforced_text = _format_enforcer(base_text)

    executor = OpenAIAssistantExecutor()
    result = await executor.ceo_command(text=enforced_text, context=safe_context)

    text_out = _pick_text(result)
    if not text_out:
        text_out = "CEO advisor nije vratio tekstualni output."

    proposed_items = None
    if isinstance(result, dict):
        proposed_items = result.get("proposed_commands")

    proposed = _to_proposed_commands(proposed_items)

    # =========================================================
    # 🔴 DEFAULT COMMAND — FRONTEND MORA IMATI BAR JEDNU AKCIJU
    # =========================================================
    if not proposed:
        proposed.append(
            ProposedCommand(
                command="refresh_snapshot",
                args={"source": "ceo_dashboard"},
                reason="No actions proposed by LLM.",
                requires_approval=True,
                risk="LOW",
                dry_run=True,
            )
        )

    trace = ctx.get("trace") if isinstance(ctx, dict) else {}
    if not isinstance(trace, dict):
        trace = {}

    trace["agent_output_text_len"] = len(text_out)
    trace["agent_router_empty_text"] = False

    return AgentOutput(
        text=text_out,
        proposed_commands=proposed,
        agent_id="ceo_advisor",
        read_only=True,
        trace=trace,
    )
