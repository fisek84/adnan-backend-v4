from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional, Tuple

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from models.canon import PROPOSAL_WRAPPER_INTENT
from services.agent_router.openai_assistant_executor import OpenAIAssistantExecutor

# PHASE 6: Import shared Notion Ops state management


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
        "nemoj izvršiti",
        "samo predloži",
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


def _llm_is_configured() -> bool:
    # Enterprise: avoid hard dependency on OpenAI for basic advisory flows.
    # If not configured, we must produce a useful deterministic response.
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    return bool(api_key)


def _is_empty_state_kickoff_prompt(user_text: str) -> bool:
    t = (user_text or "").strip().lower()
    if not t:
        return False
    # User is explicitly asking how to start from an empty state.
    return bool(
        re.search(
            r"(?i)\b(prazn\w*\s+stanj\w*|nema\s+(cilj\w*|goal\w*|task\w*|zadat\w*)|kako\s+da\s+pocn\w*|kako\s+da\s+po\u010dn\w*)\b",
            t,
        )
    )


def _default_kickoff_text() -> str:
    return (
        "Nemam učitan Notion snapshot (ciljevi/taskovi) u ovom READ kontekstu. "
        "To nije blokada — možemo krenuti odmah.\n\n"
        "Odgovori kratko na ova 3 pitanja (da bih složio top 3 cilja i top 5 taskova):\n"
        "1) Koji je glavni cilj za narednih 30 dana?\n"
        "2) Koji KPI (broj) je najvažniji da pomjeriš?\n"
        "3) Koliko sati sedmično realno imaš (npr. 5h / 10h / 20h)?\n\n"
        "U međuvremenu, evo predloženog okvira (možemo ga odmah prilagoditi):\n\n"
        "GOALS (top 3)\n"
        "1) Definiši 30-dnevni fokus | draft | high\n"
        "2) Postavi KPI target + baseline | draft | high\n"
        "3) Uvedi weekly review ritam | draft | medium\n\n"
        "TASKS (top 5)\n"
        "1) Napiši 1-paragraf cilj + kriterij uspjeha | to do | high\n"
        "2) Izaberi 1 KPI i upiši baseline | to do | high\n"
        "3) Razbij cilj na 3 deliverable-a | to do | high\n"
        "4) Zakazi weekly review (15 min) | to do | medium\n"
        "5) Kreiraj prvu sedmičnu listu top 3 taskova | to do | medium\n"
    )


def _is_prompt_preparation_request(user_text: str) -> bool:
    t = (user_text or "").strip().lower()
    if not t:
        return False
    # User wants a copy/paste template to send to Notion Ops (not a dashboard summary).
    return bool(
        re.search(
            r"(?i)\b(prompt|template|copy\s*/?\s*paste|copy\s+paste|format|formatiraj|priprem\w*\s+prompt|napis\w*\s+prompt|prompt\s+za)\b",
            t,
        )
    )


def _default_notion_ops_goal_subgoal_prompt(*, english_output: bool) -> str:
    if english_output:
        return (
            "Copy/paste this to Notion Ops (Goal + sub-goals):\n\n"
            "Create a GOAL in Notion.\n\n"
            "GOAL:\n"
            "Name: [Clear goal name]\n"
            "Status: Active\n"
            "Priority: High\n"
            "Deadline: [YYYY-MM-DD]\n"
            "Owner: [Name]\n"
            "Description: [2-4 sentences: why + scope]\n"
            "Success Metric: [number/%/definition of done]\n\n"
            "SUB-GOALS (create as GOALS and link Parent Goal = the goal above):\n"
            "1) Name: [Measurable sub-goal 1]\n   Status: Active\n   Priority: High\n   Deadline: [YYYY-MM-DD]\n   Success Metric: [criterion]\n"
            "2) Name: [Measurable sub-goal 2]\n   Status: Active\n   Priority: Medium\n   Deadline: [YYYY-MM-DD]\n   Success Metric: [criterion]\n"
            "3) Name: [Measurable sub-goal 3]\n   Status: Planned\n   Priority: Medium\n   Deadline: [YYYY-MM-DD]\n   Success Metric: [criterion]\n"
        )

    return (
        "Copy/paste ovo Notion Ops agentu (Cilj + potciljevi):\n\n"
        "Kreiraj GOAL u Notion.\n\n"
        "GOAL:\n"
        "Name: [Jasan naziv cilja]\n"
        "Status: Active\n"
        "Priority: High\n"
        "Deadline: [YYYY-MM-DD]\n"
        "Owner: [Ime]\n"
        "Description: [2-4 rečenice: zašto + scope]\n"
        "Success Metric: [broj / % / definicija gotovog]\n\n"
        "POTCILJEVI (kreiraj kao GOALS i poveži Parent Goal = gore navedeni):\n"
        "1) Name: [Potcilj 1 – mjerljiv]\n   Status: Active\n   Priority: High\n   Deadline: [YYYY-MM-DD]\n   Success Metric: [kriterij]\n"
        "2) Name: [Potcilj 2 – mjerljiv]\n   Status: Active\n   Priority: Medium\n   Deadline: [YYYY-MM-DD]\n   Success Metric: [kriterij]\n"
        "3) Name: [Potcilj 3 – mjerljiv]\n   Status: Planned\n   Priority: Medium\n   Deadline: [YYYY-MM-DD]\n   Success Metric: [kriterij]\n"
    )


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


def _is_fact_sensitive_query(user_text: str) -> bool:
    """Detect prompts that would require grounded business facts.

    We allow general coaching without snapshot, but we must not assert
    business state (blocked/at-risk/KPI counts/status) without SSOT data.
    """

    t = (user_text or "").strip().lower()
    if not t:
        return False

    risk_terms = (
        "blocked",
        "blokiran",
        "blokada",
        "at risk",
        "u riziku",
        "risk",
        "kasni",
        "kašn",
        "delayed",
        "critical",
        "kritic",
        "incident",
        "p0",
    )
    if any(s in t for s in risk_terms):
        return True

    # "status/stanje" questions become fact-sensitive when tied to goals/tasks/KPIs.
    wants_status = bool(re.search(r"(?i)\b(status|stanje|progress|napredak)\b", t))
    wants_target = bool(
        re.search(
            r"(?i)\b(cilj\w*|goal\w*|task\w*|zadat\w*|zadac\w*|kpi\w*|project\w*|projekat\w*)\b",
            t,
        )
    )
    if wants_status and wants_target:
        return True

    # Count/number queries about goals/tasks are fact-sensitive.
    wants_count = bool(re.search(r"(?i)\b(koliko|broj|how\s+many)\b", t))
    if wants_count and wants_target:
        return True

    return False


def _snapshot_has_business_facts(snapshot_payload: Dict[str, Any]) -> bool:
    if not isinstance(snapshot_payload, dict):
        return False
    if snapshot_payload.get("dashboard"):
        return True
    for k in ("goals", "tasks", "projects", "kpis", "kpi"):
        v = snapshot_payload.get(k)
        if isinstance(v, (list, dict)) and bool(v):
            return True
    return False


# -------------------------------
# Snapshot-structured mode (as-is)
# -------------------------------
def _format_enforcer(user_text: str, english_output: bool) -> str:
    base = (
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
        "- Snapshot je kontekst (input za inteligenciju). Ako nema podataka, nastavi savjetovanje.\n"
        "- Ako snapshot nema ciljeve/taskove: savjetuj kako da se krene, postavi pametna pitanja i predloži okvir.\n"
    )
    if english_output:
        return (
            base
            + "\nIMPORTANT: Respond in English (clear, concise, business tone). "
            + "Do not mix languages unless user explicitly asks.\n"
        )
    return (
        base
        + "\nVAŽNO: Odgovaraj na bosanskom / hrvatskom jeziku (jasno, poslovno). "
        + "Ne miješaj jezike osim ako korisnik izričito ne traži drugačije.\n"
    )


def _needs_structured_snapshot_answer(user_text: str) -> bool:
    t = (user_text or "").strip().lower()
    if not t:
        return True

    # IMPORTANT: propose-only is NOT structured dashboard mode
    if _is_propose_only_request(t):
        return False

    # Prompt-prep intent is advisory (not dashboard format)
    if _is_prompt_preparation_request(t):
        return False

    # Any "proposal/suggest" intent = advisory (not dashboard format).
    # This prevents structured dashboard mode from triggering on phrases like
    # "Možeš li predlagati ciljeve i taskove...".
    if (
        ("prijedlog" in t)
        or ("predlog" in t)
        or bool(
            re.search(
                r"(?i)\b(predlo\u017ei|predlozi|predlag\w*|suggest|recommend|idej\w*)\b",
                t,
            )
        )
    ):
        return False

    # If user is issuing an action (create/update/etc.), this is NOT dashboard mode.
    action_signals = (
        "napravi",
        "kreiraj",
        "create",
        "dodaj",
        "upisi",
        "azuriraj",
        "update",
        "promijeni",
        "move",
        "pošalji",
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
        "plan",
        "planovi",
        "weekly",
        "sedmica",
        "top 3",
        "top 5",
        "prikaži",
        "prikazi",
        "izlistaj",
        "sazetak",
    )
    return any(k in t for k in keywords)


def _is_show_request(user_text: str) -> bool:
    t = (user_text or "").strip().lower()
    if not t:
        return False
    show = bool(
        re.search(
            r"(?i)\b(pokazi|poka\u017ei|prika\u017ei|prikazi|izlistaj|show|list|pogledaj|procitaj|read)\b",
            t,
        )
    )
    target = bool(re.search(r"(?i)\b(cilj\w*|goal\w*|task\w*|zadat\w*|zadac\w*)\b", t))
    return show and target


def _show_target(user_text: str) -> str:
    """Returns: 'goals' | 'tasks' | 'both'."""
    t = (user_text or "").strip().lower()
    wants_goals = bool(re.search(r"(?i)\b(cilj\w*|goal\w*)\b", t))
    wants_tasks = bool(re.search(r"(?i)\b(task\w*|zadat\w*|zadac\w*)\b", t))
    if wants_goals and wants_tasks:
        return "both"
    if wants_goals:
        return "goals"
    if wants_tasks:
        return "tasks"
    return "both"


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
        lines.append("1) - | - | -")
        lines.append("2) - | - | -")
        lines.append("3) - | - | -")
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
        lines.append("1) - | - | -")
        lines.append("2) - | - | -")
        lines.append("3) - | - | -")
        lines.append("4) - | - | -")
        lines.append("5) - | - | -")
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

    if len(s) == 10 and s[4] == "-" and s[7] == "-":
        return s

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

    m = re.search(
        r"(deadline|rok|due date|duedate|due)\s*[:=]?\s*(\d{2}\.\d{2}\.\d{4})",
        t,
        re.IGNORECASE,
    )
    if m:
        return _normalize_date_iso(m.group(2))

    m = re.search(
        r"(deadline|rok|due date|duedate|due)\s*[:=]?\s*(\d{4}-\d{2}-\d{2})",
        t,
        re.IGNORECASE,
    )
    if m:
        return _normalize_date_iso(m.group(2))

    return None


def _extract_inline_goal_fields_from_name(
    name: str,
) -> Tuple[str, Optional[str], Optional[str], Optional[str]]:
    """Best-effort parser for inline goal specs in the title.

    Example input:
      "Finish this AI system faze 1, Status In progress, Priority High, Deadline 25.01.2026"

    Returns: (clean_title, status, priority, deadline_iso)
    where deadline_iso is YYYY-MM-DD or None.
    """
    s = str(name or "").strip()
    if not s:
        return "", None, None, None

    # Normalize separators to make regex simpler
    # We'll search for keywords and split title before the first keyword.
    lower = s.lower()

    # Keywords in both Bosnian and English
    status_idx = None
    for kw in (
        " status ",
        " status:",
        " status,",
        " status=",
        " status ",
        " status ",
        " status ",
        " status",
        " status.",
        " status ",
    ):
        idx = lower.find(kw)
        if idx > 0:
            status_idx = idx
            break

    # Fallback: look for common Bosnian/English tokens generically
    if status_idx is None:
        for kw in (
            " status ",
            " status:",
            " status,",
            " status=",
            " status ",
            " status",
            " status.",
        ):
            idx = lower.find(kw)
            if idx > 0:
                status_idx = idx
                break

    # If we never see any keywords, bail out
    if status_idx is None and all(
        k not in lower for k in ("priority", "prioritet", "deadline", "rok")
    ):
        return s, None, None, None

    # Title is everything before the first keyword occurrence
    first_kw_pos = len(s)
    for kw in ("status", "prioritet", "priority", "deadline", "rok"):
        pos = lower.find(kw)
        if pos != -1 and pos < first_kw_pos:
            first_kw_pos = pos
    title = s[:first_kw_pos].rstrip(" ,;-:") or s

    # Extract status
    status_match = re.search(
        r"(?i)status\s*[:=]?\s*([^,;\n]+)",
        s,
    )
    status_raw = (status_match.group(1) or "").strip() if status_match else None

    # Extract priority
    priority_match = re.search(
        r"(?i)(priority|prioritet)\s*[:=]?\s*([^,;\n]+)",
        s,
    )
    priority_raw = (priority_match.group(2) or "").strip() if priority_match else None

    # Extract deadline from the whole string using existing helper
    deadline_iso = _extract_deadline_from_text(s)

    return title, status_raw, priority_raw, deadline_iso


# -------------------------------
# Translation: create_task/create_goal -> ai_command
# -------------------------------
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
        args.get("Deadline") or args.get("deadline") or args.get("Due Date")
    )

    # If the model packed everything into the Name field (e.g. including
    # "Status In progress, Priority High, Deadline ..."), try to parse
    # those hints out and clean up the title.
    if ("Priority" not in args and "priority" not in args) or (
        "Status" not in args and "status" not in args
    ):
        clean_title, st_raw, pr_raw, inline_deadline = (
            _extract_inline_goal_fields_from_name(name)
        )
        if clean_title:
            name = clean_title
        if st_raw:
            status = _normalize_status(st_raw)
        if pr_raw:
            priority = _normalize_priority(pr_raw)
        if inline_deadline and not date_iso:
            date_iso = inline_deadline

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


def _wrap_as_proposal_wrapper(
    *, prompt: str, intent_hint: Optional[str]
) -> ProposedCommand:
    params: Dict[str, Any] = {"prompt": (prompt or "").strip()}
    if isinstance(intent_hint, str) and intent_hint.strip():
        params["intent_hint"] = intent_hint.strip()

    return ProposedCommand(
        command=PROPOSAL_WRAPPER_INTENT,
        intent=PROPOSAL_WRAPPER_INTENT,
        args=params,
        reason="Notion write intent ide kroz approval pipeline; predlažem komandu za preview/promotion.",
        requires_approval=True,
        risk="LOW",
        dry_run=True,
        scope="api_execute_raw",
    )


def _merge_base_prompt_with_args(base_prompt: str, args: Dict[str, Any]) -> str:
    """Build a prompt that preserves the user's text but also carries structured fields.

    This helps when the LLM returns structured args but the original text is sparse.
    The gateway wrapper parser expects explicit `Key: Value` pairs.
    """

    base = (base_prompt or "").strip()
    if not isinstance(args, dict) or not args:
        return base

    lines: List[str] = []
    # Prefer canonical Notion field labels.
    mapping = [
        ("Name", "Name"),
        ("title", "Name"),
        ("name", "Name"),
        ("Status", "Status"),
        ("status", "Status"),
        ("Priority", "Priority"),
        ("priority", "Priority"),
        ("Deadline", "Deadline"),
        ("deadline", "Deadline"),
        ("Due Date", "Due Date"),
        ("due_date", "Due Date"),
        ("Description", "Description"),
        ("description", "Description"),
    ]

    for src, canon in mapping:
        v = args.get(src)
        if v is None:
            continue
        val = str(v).strip()
        if not val:
            continue
        # Avoid duplicating if the base prompt already mentions the key.
        if canon.lower() in base.lower():
            continue
        lines.append(f"{canon}: {val}")

    if not lines:
        return base

    if not base:
        return "\n".join(lines)
    return base + "\n" + "\n".join(lines)


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

        # FIX: tolerate both "requires_approval" and "required_approval"
        ra = x.get("requires_approval", None)
        if ra is None:
            ra = x.get("required_approval", True)

        out.append(
            ProposedCommand(
                command=cmd,
                args=args,
                reason=str(x.get("reason") or "proposed by ceo_advisor").strip(),
                requires_approval=bool(ra),
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


def _snapshot_trace(
    *,
    raw_snapshot: Dict[str, Any],
    snapshot_payload: Dict[str, Any],
    goals: List[Dict[str, Any]],
    tasks: List[Dict[str, Any]],
    meta: Dict[str, Any],
) -> Dict[str, Any]:
    """Small, stable diagnostic block for UI/ops.

    Intentionally minimal: avoids leaking raw Notion data while still explaining
    whether snapshot was present/hydrated and what it contained.
    """

    src = None
    try:
        src = snapshot_payload.get("source")
    except Exception:
        src = None

    if not isinstance(src, str) or not src.strip():
        src = str(meta.get("snapshot_source") or "").strip() or None

    available = None
    try:
        available = snapshot_payload.get("available")
    except Exception:
        available = None

    if available is None:
        # If payload has content, treat it as available.
        available = bool(snapshot_payload)

    out: Dict[str, Any] = {
        "present_in_request": bool(raw_snapshot),
        "available": bool(available is True),
        "source": src,
        "goals_count": int(len(goals or [])),
        "tasks_count": int(len(tasks or [])),
    }

    # Optional freshness fields (only if producer provides them)
    for k in ("ttl_seconds", "age_seconds", "is_expired"):
        v = snapshot_payload.get(k) if isinstance(snapshot_payload, dict) else None
        if v is not None:
            out[k] = v

    # Presence-only (no content)
    try:
        dash = snapshot_payload.get("dashboard")
        if isinstance(dash, dict):
            out["has_dashboard"] = True
    except Exception:
        pass

    return out


# -------------------------------
# Main agent entrypoint
# -------------------------------
async def create_ceo_advisor_agent(
    agent_input: AgentInput, ctx: Dict[str, Any]
) -> AgentOutput:
    base_text = (agent_input.message or "").strip()
    if not base_text:
        base_text = "Reci ukratko šta možeš i kako mogu tražiti akciju."

    # Preferred UI output language (Bosanski / English) from metadata
    meta = agent_input.metadata if isinstance(agent_input.metadata, dict) else {}
    ui_lang_raw = str(
        meta.get("ui_output_lang") or meta.get("output_lang") or ""
    ).lower()
    english_output = ui_lang_raw.startswith("en")

    raw_snapshot = (
        agent_input.snapshot if isinstance(agent_input.snapshot, dict) else {}
    )
    snapshot_payload = _unwrap_snapshot(raw_snapshot)

    # Inicijalizacija goals i tasks
    goals, tasks = _extract_goals_tasks(snapshot_payload)

    snap_trace = _snapshot_trace(
        raw_snapshot=raw_snapshot,
        snapshot_payload=snapshot_payload,
        goals=goals,
        tasks=tasks,
        meta=meta,
    )

    structured_mode = _needs_structured_snapshot_answer(base_text)

    propose_only = _is_propose_only_request(base_text)
    wants_notion = _wants_notion_task_or_goal(base_text)
    wants_prompt_template = _is_prompt_preparation_request(base_text)

    # Grounding gate: for fact-sensitive questions, never assert state without snapshot.
    # This prevents hallucinated "blocked/at risk" type claims.
    snapshot_has_facts = _snapshot_has_business_facts(snapshot_payload)
    if _is_fact_sensitive_query(base_text) and not snapshot_has_facts:
        trace = ctx.get("trace") if isinstance(ctx, dict) else {}
        if not isinstance(trace, dict):
            trace = {}
        trace["grounding_gate"] = {
            "applied": True,
            "reason": "fact_sensitive_query_without_snapshot",
            "snapshot": snap_trace,
        }
        return AgentOutput(
            text=(
                "Ne mogu potvrditi poslovno stanje iz ovog upita jer u READ kontekstu nemam učitan SSOT snapshot. "
                "Predlog: pokreni 'refresh snapshot' ili otvori CEO Console snapshot pa ponovi pitanje."
            ),
            proposed_commands=[
                ProposedCommand(
                    command="refresh_snapshot",
                    args={"source": "ceo_advisory"},
                    reason="SSOT snapshot nije prisutan za fact-sensitive pitanje.",
                    requires_approval=True,
                    risk="LOW",
                    dry_run=True,
                )
            ],
            agent_id="ceo_advisor",
            read_only=True,
            trace=trace,
        )

    # Deterministic: for show/list requests, never rely on LLM.
    if structured_mode and _is_show_request(base_text):
        tgt = _show_target(base_text)
        # If snapshot service is present but unavailable, surface that explicitly.
        if (
            isinstance(snapshot_payload, dict)
            and snapshot_payload.get("available") is False
        ):
            err = str(snapshot_payload.get("error") or "snapshot_unavailable").strip()
            return AgentOutput(
                text=(
                    "Ne mogu učitati Notion read snapshot (read-only). "
                    f"Detalj: {err}\n\n"
                    "Pokušaj: 'refresh snapshot' ili provjeri Notion konfiguraciju (DB IDs/token)."
                ),
                proposed_commands=[
                    ProposedCommand(
                        command="refresh_snapshot",
                        args={"source": "ceo_dashboard"},
                        reason="Snapshot nije dostupan ili nije konfigurisan.",
                        requires_approval=True,
                        risk="LOW",
                        dry_run=True,
                    )
                ],
                agent_id="ceo_advisor",
                read_only=True,
                trace={"snapshot": snap_trace},
            )

        if (tgt in {"goals", "both"} and goals) or (tgt in {"tasks", "both"} and tasks):
            if tgt == "goals":
                text_out = _render_snapshot_summary(goals, [])
            elif tgt == "tasks":
                text_out = _render_snapshot_summary([], tasks)
            else:
                text_out = _render_snapshot_summary(goals, tasks)

            return AgentOutput(
                text=text_out,
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace={"snapshot": snap_trace},
            )

        # No data: give a precise read-path message instead of generic coaching.
        return AgentOutput(
            text=(
                "Trenutni snapshot nema učitane ciljeve/taskove. "
                "Ovo je READ problem (nije blokada Notion Ops).\n\n"
                "Predlog: pokreni refresh snapshot ili koristi 'Search Notion' panel da potvrdiš da DB sadrži stavke."
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
            trace={"snapshot": snap_trace},
        )

    # Continue processing normally...
    # If snapshot is empty and LLM isn't configured, return a deterministic
    # kickoff response (tests/CI and offline deployments).
    if (
        structured_mode
        and not goals
        and not tasks
        and not snapshot_payload.get("goals")
        and not snapshot_payload.get("tasks")
        and (_is_empty_state_kickoff_prompt(base_text) or not _llm_is_configured())
    ):
        kickoff = _default_kickoff_text()
        return AgentOutput(
            text=kickoff,
            proposed_commands=[
                ProposedCommand(
                    command="refresh_snapshot",
                    args={"source": "ceo_dashboard"},
                    reason="Snapshot nije prisutan u requestu (offline/CI).",
                    requires_approval=True,
                    risk="LOW",
                    dry_run=True,
                )
            ],
            agent_id="ceo_advisor",
            read_only=True,
            trace={
                "empty_snapshot": True,
                "llm_configured": False,
                "snapshot": snap_trace,
            },
        )

    # Nastavi sa ostatkom koda...
    safe_context: Dict[str, Any] = {
        "canon": {"read_only": True, "no_tools": True, "no_side_effects": True},
        "snapshot": snapshot_payload,
        "metadata": {
            **(agent_input.metadata if isinstance(agent_input.metadata, dict) else {}),
            "structured_mode": bool(structured_mode),
        },
    }

    if structured_mode:
        prompt_text = _format_enforcer(base_text, english_output)
    else:
        prompt_text = (
            f"{base_text}\n\n"
            "Ako predlaže akciju, vrati je u proposed_commands. "
            "Ne izvršavaj ništa."
        )
        if english_output:
            prompt_text += (
                "\nIMPORTANT: Respond in English (clear, concise, business tone). "
                "Do not mix languages unless user explicitly asks."
            )
        else:
            prompt_text += (
                "\nVAŽNO: Odgovaraj na bosanskom / hrvatskom jeziku (jasno, poslovno). "
                "Ne miješaj jezike osim ako korisnik izričito ne traži drugačije."
            )

    result: Dict[str, Any] = {}
    proposed_items: Any = None
    proposed: List[ProposedCommand] = []
    text_out: str = ""

    use_llm = not propose_only

    # Deterministic, enterprise-safe: if user asks for a prompt template for Notion Ops,
    # return it even in offline/CI mode (no LLM), and do not emit write proposals.
    if wants_prompt_template and wants_notion and not structured_mode:
        text_out = _default_notion_ops_goal_subgoal_prompt(
            english_output=english_output
        )
        trace = ctx.get("trace") if isinstance(ctx, dict) else {}
        if not isinstance(trace, dict):
            trace = {}
        trace["agent_output_text_len"] = len(text_out)
        trace["structured_mode"] = structured_mode
        trace["propose_only"] = propose_only
        trace["wants_notion"] = wants_notion
        trace["llm_used"] = False
        trace["snapshot"] = snap_trace
        trace["prompt_template"] = True
        return AgentOutput(
            text=text_out,
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace=trace,
        )

    if use_llm:
        try:
            if not _llm_is_configured():
                result = {"text": _default_kickoff_text(), "proposed_commands": []}
            else:
                executor = OpenAIAssistantExecutor()
                raw = await executor.ceo_command(text=prompt_text, context=safe_context)
                if isinstance(raw, dict):
                    result = raw
                else:
                    result = {"text": str(raw)}
        except Exception:
            # Enterprise fail-soft: no generic LLM error dumps to users; provide kickoff.
            result = {"text": _default_kickoff_text(), "proposed_commands": []}

        text_out = _pick_text(result) or "CEO advisor nije vratio tekstualni output."
        "- NE SMIJEŠ tvrditi status/rizik/blokade ili brojeve ciljeva/taskova ako to nije eksplicitno u snapshot-u; u tom slučaju reci da nije poznato iz snapshot-a i predloži refresh.\n"
        proposed_items = (
            result.get("proposed_commands") if isinstance(result, dict) else None
        )
        proposed = _to_proposed_commands(proposed_items)

    else:
        if structured_mode:
            text_out = _render_snapshot_summary(goals, tasks)
        else:
            text_out = "OK. Predložiću akciju (propose-only), bez izvršavanja."

    if proposed:
        first_cmd = getattr(proposed[0], "command", None)
        if first_cmd in ("create_task", "create_goal"):
            p0 = (
                proposed_items[0]
                if isinstance(proposed_items, list) and proposed_items
                else None
            )
            p0d = p0 if isinstance(p0, dict) else {}

            # IMPORTANT: for CEO Console preview, we need to preserve the original prompt
            # so gateway can extract arbitrary Notion properties (Field: Value) and let
            # the user edit them before approval.
            args0 = p0d.get("args") if isinstance(p0d, dict) else None
            args0 = args0 if isinstance(args0, dict) else {}

            merged_prompt = _merge_base_prompt_with_args(base_text, args0)
            intent_hint = "create_task" if first_cmd == "create_task" else "create_goal"

            proposed = [
                _wrap_as_proposal_wrapper(
                    prompt=merged_prompt,
                    intent_hint=intent_hint,
                )
            ]

    if wants_notion and not proposed:
        # Deterministic fallback: still preserve prompt by emitting the canonical wrapper.
        intent_hint = None
        try:
            if _wants_task(base_text):
                intent_hint = "create_task"
            elif _wants_goal(base_text):
                intent_hint = "create_goal"
        except Exception:
            intent_hint = None

        proposed = [
            _wrap_as_proposal_wrapper(prompt=base_text, intent_hint=intent_hint)
        ]

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
    trace["snapshot"] = snap_trace

    return AgentOutput(
        text=text_out,
        proposed_commands=proposed,
        agent_id="ceo_advisor",
        read_only=True,
        trace=trace,
    )
