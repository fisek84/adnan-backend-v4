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


def _needs_structured_snapshot_answer(user_text: str) -> bool:
    """
    Heuristika: samo kad korisnik traži dashboard/operativno stanje,
    forsiramo format i snapshot-only pravila.

    Sve ostalo (npr. "ko si ti", "kako radi", "šta misliš") je normalan chat.
    """
    t = (user_text or "").strip().lower()
    if not t:
        return True

    keywords = (
        "dashboard",
        "snapshot",
        "stanje",
        "status",
        "cilj",
        "ciljevi",
        "goal",
        "goals",
        "task",
        "tasks",
        "zadaci",
        "prioritet",
        "kpi",
        "leads",
        "leadovi",
        "plan",
        "planovi",
        "weekly",
        "sedmica",
        "nedelja",
        "nedjelja",
        "top 3",
        "top 5",
        "prikaži",
        "prikazi",
        "pokaži",
        "pokazi",
        "izlistaj",
        "sažetak",
        "sazetak",
    )
    return any(k in t for k in keywords)


def _extract_goals_tasks(snapshot: Dict[str, Any]) -> tuple[Any, Any]:
    """
    Podržava oba oblika:
      - snapshot.dashboard.goals/tasks
      - snapshot.goals/tasks
    """
    dashboard = snapshot.get("dashboard") if isinstance(snapshot, dict) else {}
    goals = None
    tasks = None

    if isinstance(dashboard, dict):
        goals = dashboard.get("goals")
        tasks = dashboard.get("tasks")

    if goals is None:
        goals = snapshot.get("goals") if isinstance(snapshot, dict) else None
    if tasks is None:
        tasks = snapshot.get("tasks") if isinstance(snapshot, dict) else None

    return goals, tasks


async def create_ceo_advisor_agent(
    agent_input: AgentInput, ctx: Dict[str, Any]
) -> AgentOutput:
    base_text = (agent_input.message or "").strip()
    if not base_text:
        base_text = "Reci ukratko šta možeš i kako mogu tražiti akciju."

    snapshot = agent_input.snapshot if isinstance(agent_input.snapshot, dict) else {}
    structured_mode = _needs_structured_snapshot_answer(base_text)

    # =========================================================
    # SNAPSHOT GUARD — samo za structured/dashboard upite
    # =========================================================
    goals, tasks = _extract_goals_tasks(snapshot)
    if structured_mode and not goals and not tasks:
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
                "structured_mode": True,
            },
        )

    # =========================================================
    # LLM PUT (read-only)
    # =========================================================
    safe_context: Dict[str, Any] = {
        "canon": {"read_only": True, "no_tools": True, "no_side_effects": True},
        "snapshot": snapshot,
        "metadata": agent_input.metadata
        if isinstance(agent_input.metadata, dict)
        else {},
    }

    if structured_mode:
        prompt_text = _format_enforcer(base_text)
    else:
        # Normalan chat: bez prisilnog formata.
        prompt_text = (
            f"{base_text}\n\n"
            "Odgovori prirodno i kratko (kao chatbot). "
            "Ne forsiraj GOALS/TASKS format osim ako te to eksplicitno ne pitam."
        )

    executor = OpenAIAssistantExecutor()
    result = await executor.ceo_command(text=prompt_text, context=safe_context)

    text_out = _pick_text(result) or "CEO advisor nije vratio tekstualni output."

    proposed_items = (
        result.get("proposed_commands") if isinstance(result, dict) else None
    )
    proposed = _to_proposed_commands(proposed_items)

    # Samo u structured modu dodaj default akciju (da UI ima šta ponuditi)
    if structured_mode and not proposed:
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
    trace["structured_mode"] = structured_mode

    return AgentOutput(
        text=text_out,
        proposed_commands=proposed,
        agent_id="ceo_advisor",
        read_only=True,
        trace=trace,
    )
