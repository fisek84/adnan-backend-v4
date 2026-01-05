# services/ceo_advisor_agent.py
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

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
    return "task" in t or "zad" in t or "goal" in t or "cilj" in t


def _wants_task(user_text: str) -> bool:
    t = (user_text or "").lower()
    return ("task" in t or "zad" in t) and ("goal" not in t and "cilj" not in t)


def _wants_goal(user_text: str) -> bool:
    t = (user_text or "").lower()
    return "goal" in t or "cilj" in t


# -------------------------------
# Snapshot unwrapping (CANON)
# -------------------------------
def _unwrap_snapshot(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """
    Supports both shapes:
      A) raw payload: {"goals": [...], "tasks": [...], ...}
      B) wrapper: {"ready":..., "last_sync":..., "payload": {...}, ...}
    Returns the payload dict.
    """
    if not isinstance(snapshot, dict):
        return {}
    payload = snapshot.get("payload")
    if isinstance(payload, dict):
        return payload
    return snapshot


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

    # If user is issuing an action (create/update/etc.), this is NOT dashboard mode.
    action_signals = (
        "napravi",
        "kreiraj",
        "create",
        "dodaj",
        "upisi",
        "upiši",
        "azuriraj",
        "ažuriraj",
        "update",
        "promijeni",
        "promeni",
        "move",
        "premjesti",
        "pošalji",
        "posalji",
    )
    if any(a in t for a in action_signals):
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


def _extract_goals_tasks(snapshot_payload: Dict[str, Any]) -> Tuple[Any, Any]:
    dashboard = (
        snapshot_payload.get("dashboard") if isinstance(snapshot_payload, dict) else {}
    )
    goals = None
    tasks = None

    if isinstance(dashboard, dict):
        goals = dashboard.get("goals")
        tasks = dashboard.get("tasks")

    if goals is None:
        goals = (
            snapshot_payload.get("goals")
            if isinstance(snapshot_payload, dict)
            else None
        )
    if tasks is None:
        tasks = (
            snapshot_payload.get("tasks")
            if isinstance(snapshot_payload, dict)
            else None
        )

    return goals, tasks


def _render_snapshot_summary(goals: Any, tasks: Any) -> str:
    def _safe_list(x: Any) -> List[Dict[str, Any]]:
        if isinstance(x, list):
            return [i for i in x if isinstance(i, dict)]
        return []

    g = _safe_list(goals)
    t = _safe_list(tasks)

    lines: List[str] = []
    lines.append("GOALS (top 3)")
    if not g:
        lines.append("NEMA DOVOLJNO PODATAKA U SNAPSHOT-U")
    else:
        for i, it in enumerate(g[:3], start=1):
            name = str(
                it.get("name") or it.get("Name") or it.get("title") or "-"
            ).strip()
            status = str(it.get("status") or it.get("Status") or "-").strip()
            priority = str(it.get("priority") or it.get("Priority") or "-").strip()
            lines.append(f"{i}) {name} | {status} | {priority}")

    lines.append("TASKS (top 5)")
    if not t:
        lines.append("NEMA DOVOLJNO PODATAKA U SNAPSHOT-U")
    else:
        for i, it in enumerate(t[:5], start=1):
            title = str(
                it.get("title") or it.get("Name") or it.get("name") or "-"
            ).strip()
            status = str(it.get("status") or it.get("Status") or "-").strip()
            priority = str(it.get("priority") or it.get("Priority") or "-").strip()
            lines.append(f"{i}) {title} | {status} | {priority}")

    return "\n".join(lines)


# -------------------------------
# LLM output parsing / utilities
# -------------------------------
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


def _normalize_date_iso(v: Any) -> Optional[str]:
    """
    Accepts:
      - '2025-10-01'
      - '01.10.2025' (dd.mm.yyyy)
    Returns ISO 'YYYY-MM-DD' or None.
    """
    s = str(v or "").strip()
    if not s:
        return None

    # already ISO
    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s

    # dd.mm.yyyy
    if len(s) == 10 and s[2] == "." and s[5] == ".":
        dd, mm, yyyy = s.split(".")
        if len(yyyy) == 4:
            return f"{yyyy}-{mm}-{dd}"

    return None


def _extract_deadline_from_text(text: str) -> Optional[str]:
    """
    Finds deadline/due date in the user's message.
    Supports:
      - deadline 01.10.2025
      - due date 01.10.2025
      - deadline: 2025-10-01
      - rok 01.10.2025
    Returns ISO YYYY-MM-DD or None.
    """
    t = (text or "").strip()

    # 1) dd.mm.yyyy
    m = re.search(
        r"(deadline|rok|due date|duedate|due)\s*[:=]?\s*(\d{2}\.\d{2}\.\d{4})",
        t,
        re.IGNORECASE,
    )
    if m:
        return _normalize_date_iso(m.group(2))

    # 2) yyyy-mm-dd
    m = re.search(
        r"(deadline|rok|due date|duedate|due)\s*[:=]?\s*(\d{4}-\d{2}-\d{2})",
        t,
        re.IGNORECASE,
    )
    if m:
        return _normalize_date_iso(m.group(2))

    return None


# ---------------------------------------
# Translation: create_task/create_goal -> ai_command
# ---------------------------------------
def _translate_create_task_to_ai_command(
    proposal: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not isinstance(proposal, dict):
        return None

    cmd = str(proposal.get("command") or "").strip()
    if cmd != "create_task":
        return None

    args = proposal.get("args") or {}
    if not isinstance(args, dict):
        args = {}

    title = (
        str(args.get("Name") or args.get("title") or args.get("name") or "").strip()
        or "E2E Chat Task"
    )
    priority = _normalize_priority(args.get("Priority") or args.get("priority"))
    status = _normalize_status(args.get("Status") or args.get("status"))

    date_iso = _normalize_date_iso(
        args.get("Deadline") or args.get("Due Date") or args.get("due_date")
    )
    property_specs: Dict[str, Any] = {
        "Name": {"type": "title", "text": title},
        "Priority": {"type": "select", "name": priority},
        "Status": {"type": "select", "name": status},
    }
    if date_iso:
        property_specs["Deadline"] = {"type": "date", "start": date_iso}

    return {
        "command": "notion_write",
        "intent": "create_page",
        "params": {"db_key": "tasks", "property_specs": property_specs},
    }


def _translate_create_goal_to_ai_command(
    proposal: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    if not isinstance(proposal, dict):
        return None

    cmd = str(proposal.get("command") or "").strip()
    if cmd != "create_goal":
        return None

    args = proposal.get("args") or {}
    if not isinstance(args, dict):
        args = {}

    name = (
        str(args.get("Name") or args.get("name") or args.get("title") or "").strip()
        or "E2E Chat Goal"
    )
    priority = _normalize_priority(args.get("Priority") or args.get("priority"))
    status = (
        str(args.get("Status") or args.get("status") or "Active").strip() or "Active"
    )

    date_iso = _normalize_date_iso(
        args.get("Deadline") or args.get("deadline") or args.get("Due date")
    )

    property_specs: Dict[str, Any] = {
        "Name": {"type": "title", "text": name},
        "Priority": {"type": "select", "name": priority},
        "Status": {"type": "select", "name": status},
    }
    if date_iso:
        property_specs["Deadline"] = {"type": "date", "start": date_iso}

    return {
        "command": "notion_write",
        "intent": "create_page",
        "params": {"db_key": "goals", "property_specs": property_specs},
    }


def _wrap_as_proposed_command_with_ai_command(
    ai_cmd: Dict[str, Any], reason: str, risk: str = "LOW"
) -> ProposedCommand:
    return ProposedCommand(
        command="notion_write",
        args={"ai_command": ai_cmd},
        reason=reason,
        requires_approval=True,
        risk=risk or "LOW",
        dry_run=True,
    )


def _to_proposed_commands(items: Any) -> List[ProposedCommand]:
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

        if isinstance(intent, str) and intent.strip() and isinstance(params, dict):
            args = dict(args)
            args.setdefault(
                "ai_command",
                {"command": cmd, "intent": intent.strip(), "params": params},
            )

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


def _deterministic_notion_ai_command_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Deterministic fallback when LLM is unavailable OR returns no usable proposed_commands.
    Only creates *proposal* (approval-gated), no execution.
    """
    base = (text or "").strip()
    if not base:
        return None

    deadline_iso = _extract_deadline_from_text(base)

    if _wants_task(base):
        property_specs: Dict[str, Any] = {
            "Name": {"type": "title", "text": "E2E Chat Task"},
            "Priority": {"type": "select", "name": "High"},
            "Status": {"type": "select", "name": "To Do"},
        }
        if deadline_iso:
            property_specs["Deadline"] = {"type": "date", "start": deadline_iso}

        return {
            "command": "notion_write",
            "intent": "create_page",
            "params": {"db_key": "tasks", "property_specs": property_specs},
        }

    if _wants_goal(base):
        property_specs: Dict[str, Any] = {
            "Name": {"type": "title", "text": "E2E Chat Goal"},
            "Priority": {"type": "select", "name": "High"},
            "Status": {"type": "select", "name": "Active"},
        }
        if deadline_iso:
            property_specs["Deadline"] = {"type": "date", "start": deadline_iso}

        return {
            "command": "notion_write",
            "intent": "create_page",
            "params": {"db_key": "goals", "property_specs": property_specs},
        }

    return None


# -------------------------------
# Main agent entrypoint
# -------------------------------
async def create_ceo_advisor_agent(
    agent_input: AgentInput, ctx: Dict[str, Any]
) -> AgentOutput:
    base_text = (agent_input.message or "").strip()
    if not base_text:
        base_text = "Reci ukratko šta možeš i kako mogu tražiti akciju."

    raw_snapshot = (
        agent_input.snapshot if isinstance(agent_input.snapshot, dict) else {}
    )
    snapshot_payload = _unwrap_snapshot(raw_snapshot)

    structured_mode = _needs_structured_snapshot_answer(base_text)

    propose_only = _is_propose_only_request(base_text)
    wants_notion = _wants_notion_task_or_goal(base_text)

    # =========================================================
    # SNAPSHOT GUARD — only for structured dashboard requests
    # =========================================================
    goals, tasks = _extract_goals_tasks(snapshot_payload)
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
                "structured_mode": True,
                "snapshot_wrapper_present": isinstance(
                    raw_snapshot.get("payload"), dict
                ),
                "snapshot_ready": raw_snapshot.get("ready"),
                "snapshot_last_sync": raw_snapshot.get("last_sync")
                or snapshot_payload.get("last_sync"),
                "snapshot_source": (agent_input.metadata or {}).get("snapshot_source")
                if isinstance(agent_input.metadata, dict)
                else None,
            },
        )

    # =========================================================
    # LLM PUT (read-only) — GUARDED (CI-safe)
    # =========================================================
    safe_context: Dict[str, Any] = {
        "canon": {"read_only": True, "no_tools": True, "no_side_effects": True},
        # IMPORTANT: give LLM the SSOT payload (not wrapper noise)
        "snapshot": snapshot_payload,
        "metadata": agent_input.metadata
        if isinstance(agent_input.metadata, dict)
        else {},
    }

    if structured_mode:
        prompt_text = _format_enforcer(base_text)
    else:
        prompt_text = (
            f"{base_text}\n\n"
            "Ako predlažeš akciju, vrati je u proposed_commands. "
            "Ne izvršavaj ništa."
        )

    result: Dict[str, Any] = {}
    proposed_items: Any = None
    proposed: List[ProposedCommand] = []
    text_out: str = ""

    # keep propose-only deterministic (no OpenAI dependency)
    use_llm = not propose_only

    if use_llm:
        try:
            executor = OpenAIAssistantExecutor()
            raw = await executor.ceo_command(text=prompt_text, context=safe_context)
            if isinstance(raw, dict):
                result = raw
            else:
                result = {"text": str(raw)}
        except Exception as e:
            result = {"text": f"LLM unavailable: {e}"}

        text_out = _pick_text(result) or "CEO advisor nije vratio tekstualni output."
        proposed_items = (
            result.get("proposed_commands") if isinstance(result, dict) else None
        )
        proposed = _to_proposed_commands(proposed_items)
    else:
        if structured_mode:
            text_out = _render_snapshot_summary(goals, tasks)
        else:
            text_out = "OK. Predložiću akciju (propose-only), bez izvršavanja."

    # =========================================================
    # CANON: always ensure Notion write requests can produce a deterministic proposal
    # =========================================================

    # 1) If LLM returned create_task/create_goal, translate to notion_write ai_command
    if proposed:
        first_cmd = getattr(proposed[0], "command", None)
        if first_cmd in ("create_task", "create_goal"):
            p0 = (
                proposed_items[0]
                if isinstance(proposed_items, list) and proposed_items
                else None
            )
            p0d = p0 if isinstance(p0, dict) else {}

            ai_cmd = None
            if first_cmd == "create_task":
                ai_cmd = _translate_create_task_to_ai_command(p0d)
            elif first_cmd == "create_goal":
                ai_cmd = _translate_create_goal_to_ai_command(p0d)

            if isinstance(ai_cmd, dict):
                proposed = [
                    _wrap_as_proposed_command_with_ai_command(
                        ai_cmd,
                        reason=f"Translated {first_cmd} -> notion_write/{ai_cmd.get('intent')} (args.ai_command) for approval-gated execution.",
                        risk="LOW",
                    )
                ]

    # 2) If user wants Notion action and we have no usable proposal -> deterministic fallback proposal
    if wants_notion and not proposed:
        ai_cmd = _deterministic_notion_ai_command_from_text(base_text)
        if isinstance(ai_cmd, dict):
            proposed = [
                _wrap_as_proposed_command_with_ai_command(
                    ai_cmd,
                    reason="Deterministic Notion proposal (approval-gated).",
                    risk="LOW",
                )
            ]

    # 3) Structured-mode default action (only when NOT a Notion write ask)
    if structured_mode and (not wants_notion) and not proposed:
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
    trace["llm_used"] = use_llm
    trace["snapshot_wrapper_present"] = isinstance(raw_snapshot.get("payload"), dict)
    trace["snapshot_ready"] = raw_snapshot.get("ready")
    trace["snapshot_last_sync"] = raw_snapshot.get("last_sync") or snapshot_payload.get(
        "last_sync"
    )
    trace["snapshot_source"] = (
        (agent_input.metadata or {}).get("snapshot_source")
        if isinstance(agent_input.metadata, dict)
        else None
    )

    return AgentOutput(
        text=text_out,
        proposed_commands=proposed,
        agent_id="ceo_advisor",
        read_only=True,
        trace=trace,
    )
