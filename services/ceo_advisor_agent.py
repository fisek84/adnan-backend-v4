from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
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

    # "prijedlog/predlog" = advisory (ne dashboard format)
    if ("prijedlog" in t) or ("predlog" in t):
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

    structured_mode = _needs_structured_snapshot_answer(base_text)

    propose_only = _is_propose_only_request(base_text)
    wants_notion = _wants_notion_task_or_goal(base_text)

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
                trace={},
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
                trace={},
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
            trace={},
        )

    # Continue processing normally...
    # Only treat as "prazno" when snapshot itself is missing or explicitly empty,
    # and there are truly no goals or tasks parsed out.
    if (
        structured_mode
        and not goals
        and not tasks
        and not snapshot_payload.get("goals")
        and not snapshot_payload.get("tasks")
    ):
        return AgentOutput(
            text=(  # Ovo je deo za prazno stanje
                "Vidim da je stanje prazno (nema ciljeva ni taskova u snapshot-u). To nije blokada — krenimo od brzog okvira.\n\n"
                "Krenimo: odgovori na 2-3 pitanja iznad, pa cu ti složiti top 3 cilja i top 5 taskova u istom formatu.\n"
            ),
            proposed_commands=[  # Predlog za akciju
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
            trace={},
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

    return AgentOutput(
        text=text_out,
        proposed_commands=proposed,
        agent_id="ceo_advisor",
        read_only=True,
        trace=trace,
    )
