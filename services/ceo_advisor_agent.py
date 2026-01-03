# services/ceo_advisor_agent.py
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple, Optional

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from services.agent_router.openai_assistant_executor import OpenAIAssistantExecutor

# -----------------------------------
# Detection (propose-only / notion ask)
# -----------------------------------
def _is_propose_only_request(user_text: str) -> bool:
    t = (user_text or "").strip().lower()
    if not t:
        return False
    signals = (
        "propose",
        "proposed_commands",
        "do not execute",
        "ne izvršavaj",
        "ne izvrsavaj",
        "nemoj izvršiti",
        "nemoj izvrsiti",
        "samo predloži",
        "samo predlozi",
        "return proposed",
    )
    return any(s in t for s in signals)

def _wants_notion_task_or_goal(user_text: str) -> bool:
    t = (user_text or "").lower()
    if "notion" not in t:
        return False
    return ("task" in t or "zad" in t or "goal" in t or "cilj" in t)

def _wants_task(user_text: str) -> bool:
    t = (user_text or "").lower()
    return ("task" in t or "zad" in t) and ("goal" not in t and "cilj" not in t)

def _wants_goal(user_text: str) -> bool:
    t = (user_text or "").lower()
    return ("goal" in t or "cilj" in t)

# -------------------------------
# Snapshot-structured mode (as-is)
# -------------------------------
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
    t = (user_text or "").strip().lower()
    if not t:
        return True

    # IMPORTANT: propose-only is NOT structured dashboard mode
    if _is_propose_only_request(t):
        return False

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

def _extract_goals_tasks(snapshot: Dict[str, Any]) -> Tuple[Any, Any]:
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

# -------------------------------
# LLM output parsing / utilities
# -------------------------------
def _pick_text(result: Any) -> str:
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

def _normalize_priority(v: Any) -> str:
    s = str(v or "").strip()
    if not s:
        return "High"
    s_low = s.lower()
    if s_low in ("high", "h", "visok", "visoka"):
        return "High"
    if s_low in ("medium", "m", "srednji", "srednja"):
        return "Medium"
    if s_low in ("low", "l", "nizak", "niska"):
        return "Low"
    # passthrough but TitleCase common
    return s[:1].upper() + s[1:]

def _normalize_status(v: Any) -> str:
    s = str(v or "").strip()
    if not s:
        return "To Do"
    s_low = s.lower()
    if s_low in ("to do", "todo", "uraditi"):
        return "To Do"
    if s_low in ("in progress", "u toku"):
        return "In Progress"
    if s_low in ("done", "completed", "završeno", "zavrseno"):
        return "Done"
    return s

# ---------------------------------------
# Translation: create_task -> ai_command
# ---------------------------------------
def _translate_create_task_to_ai_command(proposal: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """
    Accepts proposal dict like:
      { "command": "create_task", "args": {"Name": "...", "Priority": "...", "Status": "..."} }
    and returns ai_command dict for notion_write/create_page.
    """
    if not isinstance(proposal, dict):
        return None

    cmd = str(proposal.get("command") or "").strip()
    if cmd != "create_task":
        return None

    args = proposal.get("args") or {}
    if not isinstance(args, dict):
        args = {}

    title = str(args.get("Name") or args.get("title") or args.get("name") or "").strip() or "E2E Chat Task"
    priority = _normalize_priority(args.get("Priority") or args.get("priority"))
    status = _normalize_status(args.get("Status") or args.get("status"))

    return {
        "command": "notion_write",
        "intent": "create_page",
        "params": {
            "db_key": "tasks",
            "property_specs": {
                "Name": {"type": "title", "text": title},
                "Priority": {"type": "select", "name": priority},
                "Status": {"type": "select", "name": status},
            },
        },
    }

def _wrap_as_proposed_command_with_ai_command(ai_cmd: Dict[str, Any], reason: str, risk: str = "LOW") -> ProposedCommand:
    return ProposedCommand(
        command="notion_write",
        args={"ai_command": ai_cmd},
        reason=reason,
        requires_approval=True,
        risk=risk or "LOW",
        dry_run=True,
    )

def _to_proposed_commands(items: Any) -> List[ProposedCommand]:
    """
    Normalizes list of dicts into ProposedCommand objects.
    Also supports LLM returning raw executable {command,intent,params} by wrapping into args.ai_command.
    """
    if not isinstance(items, list):
        return []

    out: List[ProposedCommand] = []
    for x in items:
        if not isinstance(x, dict):
            continue
        cmd = str(x.get("command") or x.get("command_type") or "").strip()
        if not cmd:
            continue

        args = x.get("args") or x.get("payload") or {}
        if not isinstance(args, dict):
            args = {}

        intent = x.get("intent")
        params = x.get("params")

        # If LLM returns executable raw triple, wrap into ai_command
        if isinstance(intent, str) and intent.strip() and isinstance(params, dict):
            args = dict(args)
            args.setdefault("ai_command", {"command": cmd, "intent": intent.strip(), "params": params})

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

# -------------------------------
# Main agent entrypoint
# -------------------------------
async def create_ceo_advisor_agent(agent_input: AgentInput, ctx: Dict[str, Any]) -> AgentOutput:
    base_text = (agent_input.message or "").strip()
    if not base_text:
        base_text = "Reci ukratko šta možeš i kako mogu tražiti akciju."

    snapshot = agent_input.snapshot if isinstance(agent_input.snapshot, dict) else {}
    structured_mode = _needs_structured_snapshot_answer(base_text)

    propose_only = _is_propose_only_request(base_text)
    wants_notion = _wants_notion_task_or_goal(base_text)

    # =========================================================
    # SNAPSHOT GUARD — only for structured dashboard requests
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
        "metadata": agent_input.metadata if isinstance(agent_input.metadata, dict) else {},
    }

    if structured_mode:
        prompt_text = _format_enforcer(base_text)
    else:
        prompt_text = (
            f"{base_text}\n\n"
            "Ako predlažeš akciju, vrati je u proposed_commands. "
            "Ne izvršavaj ništa."
        )

    executor = OpenAIAssistantExecutor()
    result = await executor.ceo_command(text=prompt_text, context=safe_context)

    text_out = _pick_text(result) or "CEO advisor nije vratio tekstualni output."
    proposed_items = result.get("proposed_commands") if isinstance(result, dict) else None
    proposed = _to_proposed_commands(proposed_items)

    # =========================================================
    # CANON: translate create_task -> notion_write executable ai_command
    # =========================================================
    if propose_only and wants_notion:
        # If LLM gave create_task, convert it into args.ai_command (executable)
        if proposed and getattr(proposed[0], "command", None) == "create_task":
            p0 = proposed_items[0] if isinstance(proposed_items, list) and proposed_items else None
            ai_cmd = _translate_create_task_to_ai_command(p0 if isinstance(p0, dict) else {})
            if isinstance(ai_cmd, dict):
                proposed = [
                    _wrap_as_proposed_command_with_ai_command(
                        ai_cmd,
                        reason="Translated create_task -> notion_write/create_page (args.ai_command) for /api/proposals/execute compatibility.",
                        risk="LOW",
                    )
                ]
                text_out = text_out or "Translated proposal into executable Notion write command."

        # If LLM gave nothing usable, force a deterministic executable proposal for tasks/goals
        if not proposed or (proposed and getattr(proposed[0], "command", None) in ("refresh_snapshot",)):
            # Minimal deterministic fallback only for task creation requests
            if _wants_task(base_text):
                ai_cmd = {
                    "command": "notion_write",
                    "intent": "create_page",
                    "params": {
                        "db_key": "tasks",
                        "property_specs": {
                            "Name": {"type": "title", "text": "E2E Chat Task"},
                            "Priority": {"type": "select", "name": "High"},
                            "Status": {"type": "select", "name": "To Do"},
                        },
                    },
                }
                proposed = [
                    _wrap_as_proposed_command_with_ai_command(
                        ai_cmd,
                        reason="Deterministic propose-only Notion task command (snapshot not required).",
                        risk="LOW",
                    )
                ]
            elif _wants_goal(base_text):
                ai_cmd = {
                    "command": "notion_write",
                    "intent": "create_page",
                    "params": {
                        "db_key": "goals",
                        "property_specs": {
                            "Name": {"type": "title", "text": "E2E Chat Goal"},
                            "Priority": {"type": "select", "name": "High"},
                            "Status": {"type": "select", "name": "Active"},
                        },
                    },
                }
                proposed = [
                    _wrap_as_proposed_command_with_ai_command(
                        ai_cmd,
                        reason="Deterministic propose-only Notion goal command (snapshot not required).",
                        risk="LOW",
                    )
                ]

    # Structured-mode default action
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
    trace["propose_only"] = propose_only
    trace["wants_notion"] = wants_notion

    return AgentOutput(
        text=text_out,
        proposed_commands=proposed,
        agent_id="ceo_advisor",
        read_only=True,
        trace=trace,
    )
