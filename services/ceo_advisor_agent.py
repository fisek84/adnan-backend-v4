from __future__ import annotations

import os
import re
import hashlib
import json
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from models.agent_contract import AgentInput, AgentOutput, ProposedCommand
from models.canon import PROPOSAL_WRAPPER_INTENT

from services.intent_precedence import classify_intent

# PHASE 6: Import shared Notion Ops state management
from services.notion_ops_state import get_state as get_notion_ops_state
from services.notion_ops_state import is_armed as notion_ops_is_armed


_CEO_INSTRUCTIONS_PREFIX = "CEO ADVISOR — RESPONSES SYSTEM INSTRUCTIONS (READ-ONLY)"


def _sha256_prefix(text: str, *, limit: int = 1000) -> str:
    s = (text or "")[: max(0, int(limit))]
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _truncate(text: str, *, max_chars: int) -> str:
    t = text or ""
    if max_chars <= 0:
        return "[TRUNCATED]"
    if len(t) <= max_chars:
        return t
    keep = max(0, max_chars - len("[TRUNCATED]"))
    return t[:keep] + "[TRUNCATED]"


def build_ceo_instructions(
    grounding_pack: Dict[str, Any],
    conversation_state: Optional[str] = None,
    notion_ops: Optional[Dict[str, Any]] = None,
    *,
    kb_max_entries: int = 8,
    total_max_chars: int = 9000,
    section_max_chars: int = 2600,
    kb_entry_max_chars: int = 800,
) -> str:
    """Build deterministic, budgeted system-equivalent instructions for CEO Advisor.

    Invariants:
    - Deterministic (no LLM).
    - Budgeted and safe (no raw huge dumps).
    - Explicit governance: answer ONLY from provided context.
    """

    gp = grounding_pack if isinstance(grounding_pack, dict) else {}

    def _dump(obj: Any, *, max_chars: int) -> str:
        try:
            raw = json.dumps(obj, ensure_ascii=False, sort_keys=True)
        except Exception:
            raw = str(obj)
        return _truncate(raw, max_chars=max_chars)

    identity_payload = None
    kb_entries: list[dict[str, Any]] = []
    notion_snapshot = None
    memory_payload = None
    conv_state_txt = None

    ip = gp.get("identity_pack") if isinstance(gp.get("identity_pack"), dict) else {}
    if isinstance(ip, dict):
        identity_payload = ip.get("payload")

    kb = gp.get("kb_retrieved") if isinstance(gp.get("kb_retrieved"), dict) else {}
    if isinstance(kb, dict):
        entries = kb.get("entries")
        if isinstance(entries, list):
            for it in entries:
                if isinstance(it, dict):
                    kb_entries.append(it)

    ns = gp.get("notion_snapshot")
    if isinstance(ns, dict):
        notion_snapshot = ns

    ms = (
        gp.get("memory_snapshot") if isinstance(gp.get("memory_snapshot"), dict) else {}
    )
    if isinstance(ms, dict):
        mp = ms.get("payload")
        if isinstance(mp, dict):
            memory_payload = mp

    kb_has_hits = len(kb_entries) > 0

    # Governance / hard constraints.
    if kb_has_hits:
        governance = (
            "GOVERNANCE (non-negotiable):\n"
            "- READ-ONLY: no tool calls, no side effects, no external writes.\n"
            "- KB-FIRST: Prefer KB_CONTEXT for curated knowledge/policies, BUT you MAY use NOTION_SNAPSHOT for factual state questions about Notion (e.g. do we have goals/tasks/projects, counts, presence).\n"
            "- DO NOT use general world knowledge.\n"
            "- For Notion state questions: if NOTION_SNAPSHOT is present, answer from it and do NOT respond with 'Nemam u KB/Memory/Snapshot'.\n"
            "- NOTION READ SNAPSHOT: If NOTION_SNAPSHOT is present/ready, you DO have access to it regardless of NOTION_OPS_STATE.armed; use it for situational awareness.\n"
            "- If you propose actions, put them into proposed_commands but do not execute anything.\n"
            "- NOTION WRITES: Only propose Notion write commands when NOTION_OPS_STATE.armed == true. If armed==false, ask the user to arm Notion Ops ('notion ops aktiviraj') instead of proposing writes.\n"
        )
    else:
        governance = (
            "GOVERNANCE (non-negotiable):\n"
            "- READ-ONLY: no tool calls, no side effects, no external writes.\n"
            "- Answer ONLY from the provided context sections below (IDENTITY, KB_CONTEXT, NOTION_SNAPSHOT, MEMORY_CONTEXT).\n"
            "- DO NOT use general world knowledge. If the answer is not in the provided context, say: 'Nemam u KB/Memory/Snapshot'.\n"
            "- NOTION READ SNAPSHOT: If NOTION_SNAPSHOT is present/ready, you DO have access to it regardless of NOTION_OPS_STATE.armed; use it for situational awareness and do NOT ask to enable snapshot.\n"
            "- If you propose actions, put them into proposed_commands but do not execute anything.\n"
            "- NOTION WRITES: Only propose Notion write commands when NOTION_OPS_STATE.armed == true. If armed==false, ask the user to arm Notion Ops ('notion ops aktiviraj') instead of proposing writes.\n"
        )

    notion_ops_txt = "(missing)"
    if isinstance(notion_ops, dict) and notion_ops:
        notion_ops_txt = _dump(notion_ops, max_chars=1200)

    # IDENTITY section (budgeted dump).
    identity_txt = "(missing)"
    if kb_has_hits:
        identity_txt = "(omitted: KB-first)"
    elif identity_payload is not None:
        identity_txt = _dump(identity_payload, max_chars=section_max_chars)

    # KB_HITS section: top N, budgeted per-entry.
    kb_lines: list[str] = []
    for it in kb_entries[: max(0, int(kb_max_entries))]:
        kid = it.get("id")
        title = it.get("title")
        content = it.get("content")
        line_obj = {
            "id": kid,
            "title": title,
            "tags": it.get("tags"),
            "priority": it.get("priority"),
            "content": content,
        }
        kb_lines.append(_dump(line_obj, max_chars=kb_entry_max_chars))
    kb_txt = "(none)" if not kb_lines else "\n".join(kb_lines)
    kb_txt = _truncate(kb_txt, max_chars=section_max_chars)

    # NOTION snapshot (budgeted dump).
    notion_txt = "(missing)"
    if notion_snapshot is not None:
        notion_txt = _dump(notion_snapshot, max_chars=section_max_chars)

    # MEMORY snapshot payload (budgeted dump).
    memory_txt = "(missing)"
    if kb_has_hits:
        memory_txt = "(omitted: KB-first)"
    elif memory_payload is not None:
        memory_txt = _dump(memory_payload, max_chars=section_max_chars)

    if isinstance(conversation_state, str) and conversation_state.strip():
        conv_state_txt = _truncate(
            conversation_state.strip(), max_chars=section_max_chars
        )

    parts = [
        _CEO_INSTRUCTIONS_PREFIX,
        governance.strip(),
        "NOTION_OPS_STATE:\n" + notion_ops_txt,
        "IDENTITY:\n" + identity_txt,
        "KB_CONTEXT:\n" + kb_txt,
        "CONVERSATION_STATE:\n" + (conv_state_txt or "(none)"),
        "NOTION_SNAPSHOT:\n" + notion_txt,
        "MEMORY_CONTEXT:\n" + memory_txt,
    ]

    joined = "\n\n".join(parts).strip() + "\n"
    joined = _truncate(joined, max_chars=total_max_chars)
    return joined


def _business_plan_template_with_questions(*, english_output: bool) -> str:
    if english_output:
        return (
            "BUSINESS PLAN — 1-page template (fill-in)\n"
            "\n"
            "1) Problem & Customer\n"
            "- Problem: ____\n"
            "- Target customer: ____\n"
            "- Why now: ____\n"
            "\n"
            "2) Solution & Value Proposition\n"
            "- Solution (1 sentence): ____\n"
            "- Differentiator: ____\n"
            "- Proof/credibility: ____\n"
            "\n"
            "3) Market & Competition\n"
            "- Market segment: ____\n"
            "- Alternatives/competitors: ____\n"
            "- Your advantage: ____\n"
            "\n"
            "4) Go-to-Market (GTM)\n"
            "- Offer: ____\n"
            "- Pricing: ____\n"
            "- Channels: ____\n"
            "- Sales motion: ____\n"
            "\n"
            "5) Operations\n"
            "- Team/roles: ____\n"
            "- Delivery process: ____\n"
            "- Tools/resources: ____\n"
            "\n"
            "6) Financials\n"
            "- Revenue model: ____\n"
            "- Main costs: ____\n"
            "- Unit economics (rough): ____\n"
            "\n"
            "7) 30/60/90-day plan + KPIs\n"
            "- 30d: ____ (KPI: ____)\n"
            "- 60d: ____ (KPI: ____)\n"
            "- 90d: ____ (KPI: ____)\n"
            "\n"
            "Questions to answer (quick):\n"
            "- Who exactly is the customer and what is the urgent pain?\n"
            "- What are you selling first (offer) and why will they buy now?\n"
            "- What channel will you use first, and what is the first sales step?\n"
            "- What are the top 3 assumptions and how will you test them in 7 days?\n"
            "- What is your target KPI for 30/60/90 days?\n"
        )
    return (
        "BIZNIS PLAN — minimalni 1-page template (za popunu)\n"
        "\n"
        "1) Problem i ciljna grupa\n"
        "- Problem (jedna rečenica): ____\n"
        "- Ciljni kupac (ko tačno): ____\n"
        "- Zašto sad (hitnost): ____\n"
        "\n"
        "2) Rješenje i value proposition\n"
        "- Rješenje (jedna rečenica): ____\n"
        "- Diferencijator (zašto baš mi): ____\n"
        "- Dokaz/credibility: ____\n"
        "\n"
        "3) Tržište i konkurencija\n"
        "- Segment tržišta: ____\n"
        "- Alternative/konkurenti: ____\n"
        "- Naša prednost: ____\n"
        "\n"
        "4) GTM (go-to-market)\n"
        "- Ponuda (šta tačno prodaješ): ____\n"
        "- Cijene/paketi: ____\n"
        "- Kanali (1–2 prva): ____\n"
        "- Prodajni tok (prvi korak): ____\n"
        "\n"
        "5) Operacije\n"
        "- Tim i uloge: ____\n"
        "- Proces isporuke: ____\n"
        "- Alati/resursi: ____\n"
        "\n"
        "6) Finansije\n"
        "- Model prihoda: ____\n"
        "- Glavni troškovi: ____\n"
        "- Unit economics (grubo): ____\n"
        "\n"
        "7) 30/60/90 dana + KPI\n"
        "- 30d: ____ (KPI: ____)\n"
        "- 60d: ____ (KPI: ____)\n"
        "- 90d: ____ (KPI: ____)\n"
        "\n"
        "Pitanja za popunu (brzo):\n"
        "- Ko je tačno kupac i koji je urgentan problem?\n"
        "- Šta je prva ponuda (MVP/offer) i zašto će kupiti sada?\n"
        "- Koji je prvi kanal i koji je prvi prodajni korak?\n"
        "- Koje su top 3 pretpostavke i kako ih testiraš u 7 dana?\n"
        "- Koji KPI target imaš za 30/60/90 dana?\n"
    )


def _responses_mode_enabled() -> bool:
    return (os.getenv("OPENAI_API_MODE") or "assistants").strip().lower() == "responses"


def _grounding_sufficient_for_responses_llm(gp: Any) -> bool:
    if not isinstance(gp, dict) or not gp:
        return False
    if gp.get("enabled") is False:
        return False

    ip = gp.get("identity_pack") if isinstance(gp.get("identity_pack"), dict) else {}
    if not isinstance(ip, dict) or not ip:
        return False
    if ip.get("payload") is None:
        return False

    kb = gp.get("kb_retrieved") if isinstance(gp.get("kb_retrieved"), dict) else None
    if not isinstance(kb, dict):
        return False
    if not isinstance(kb.get("entries"), list):
        return False

    if not isinstance(gp.get("notion_snapshot"), dict):
        return False

    ms = (
        gp.get("memory_snapshot")
        if isinstance(gp.get("memory_snapshot"), dict)
        else None
    )
    if not isinstance(ms, dict):
        return False
    if not isinstance(ms.get("payload"), dict):
        return False

    return True


def _responses_missing_grounding_text(*, english_output: bool) -> str:
    if english_output:
        return (
            "I don't have the required grounding context (KB/Memory/Snapshot) in this request. "
            "Nemam u KB/Memory/Snapshot."
        )
    return "Nemam u KB/Memory/Snapshot za ovaj upit (u ovom READ kontekstu nije dostavljen grounding)."


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


def _has_explicit_action_for_goal_task(user_text: str) -> tuple[bool, str]:
    """Detect explicit imperative action for goal/task.

    Returns:
      (True, "goal") or (True, "task") only when BOTH are present in the same string:
      - ACTION_VERB (word-boundary)
      - TARGET (word-boundary)
    Otherwise returns (False, "").
    """

    t = (user_text or "").strip().lower()
    if not t:
        return (False, "")

    action_re = r"(?i)\b(kreiraj|napravi|dodaj|upi\u0161i|upisi|unesi|postavi|set|create|add|write)\b"
    if not re.search(action_re, t):
        return (False, "")

    goal_re = r"(?i)\b(cilj|goal)\b"
    task_re = r"(?i)\b(task|zad|zadatak)\b"

    if re.search(goal_re, t):
        return (True, "goal")
    if re.search(task_re, t):
        return (True, "task")
    return (False, "")


def _wants_notion_task_or_goal(user_text: str) -> bool:
    t = (user_text or "").lower()
    if "notion" not in t:
        return False
    ok, kind = _has_explicit_action_for_goal_task(t)
    return bool(ok and kind in {"goal", "task"})


def _defers_notion_execution_or_wants_discussion_first(user_text: str) -> bool:
    """True when the user explicitly says: not now / let's talk first / prep/analysis.

    This is used to avoid short-circuiting into the SSOT snapshot_read_summary
    response for planning/discussion prompts.
    """

    t = (user_text or "").strip().lower()
    if not t:
        return False

    # Direct "talk first" markers.
    if any(
        s in t
        for s in (
            "prvo razgovaramo",
            "prvo da razgovaramo",
            "prvo razgovor",
            "prvo da popricamo",
            "prvo da popričamo",
            "prvo da pricamo",
            "da prvo razgovaramo",
            "let's talk first",
            "lets talk first",
            "before we do that",
        )
    ):
        return True

    # "Not now" markers, typically paired with execution verbs.
    not_now = any(
        s in t
        for s in (
            "neću sad",
            "necu sad",
            "neću sada",
            "necu sada",
            "ne sada",
            "ne sad",
            "neću još",
            "necu jos",
            "neću jos",
            "ne jos",
        )
    )
    if not_now and any(
        v in t
        for v in (
            "postav",
            "podes",
            "upi",
            "upis",
            "unes",
            "kreir",
            "dodaj",
            "napravi",
            "set ",
            "create ",
            "write ",
        )
    ):
        return True

    # Prep/analysis wording that implies discussion before execution.
    if any(s in t for s in ("priprem", "priprema", "razrad", "razrada")) and any(
        s in t for s in ("prvo", "before", "najprije", "najpre")
    ):
        return True

    return False


def _wants_task(user_text: str) -> bool:
    ok, kind = _has_explicit_action_for_goal_task(user_text)
    return bool(ok and kind == "task")


def _wants_goal(user_text: str) -> bool:
    ok, kind = _has_explicit_action_for_goal_task(user_text)
    return bool(ok and kind == "goal")


def _llm_is_configured() -> bool:
    # Explicit offline/disable flag.
    if (os.getenv("CEO_ADVISOR_FORCE_OFFLINE") or "").strip() == "1":
        return False
    # Enterprise: avoid hard dependency on OpenAI for basic advisory flows.
    # If not configured, we must produce a useful deterministic response.
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    return bool(api_key)


class LLMNotConfiguredError(RuntimeError):
    """Raised when the request expects LLM execution but no LLM is configured."""


def _strict_llm_required(meta: Any) -> bool:
    """Whether missing LLM configuration should be treated as an error.

    Default behavior (especially under tests/CI) is to stay deterministic and
    return an offline-safe response.
    """

    strict_env = (os.getenv("CEO_ADVISOR_STRICT_LLM") or "").strip().lower()
    if strict_env in {"1", "true", "yes", "on"}:
        return True

    if isinstance(meta, dict):
        # Allow callers to request strict behavior per-request.
        if meta.get("strict_llm") is True or meta.get("require_llm") is True:
            return True

    return False


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


def _is_memory_capability_question(user_text: str) -> bool:
    t = (user_text or "").strip().lower()
    if not t:
        return False
    # Questions about whether the system can remember/store info.
    return bool(
        re.search(
            r"(?i)\b(mo\u017ee\u0161\s+li\s+pamt\w*|mozes\s+li\s+pamt\w*|da\s+li\s+pamt\w*|pamti\u0161|pamtis|pamti\u0161\s+li|pamtis\s+li|memorij\w*|memory)\b",
            t,
        )
    ) and not bool(
        re.search(
            r"(?i)\b(zapamti|remember\s+this|pro\u0161iri\s+znanje|prosiri\s+znanje|nau\u010di)\b",
            t,
        )
    )


def _is_memory_write_request(user_text: str) -> bool:
    t = (user_text or "").strip().lower()
    if not t:
        return False
    return bool(re.search(r"(?i)\b(zapamti|remember\s+this|nau\u010di)\b", t))


def _is_expand_knowledge_request(user_text: str) -> bool:
    t = (user_text or "").strip().lower()
    if not t:
        return False
    return bool(
        re.search(
            r"(?i)\b(pro\u0161iri\s+znanje|prosiri\s+znanje|pro\u0161irenje\s+znanja)\b",
            t,
        )
    )


def _is_trace_status_query(user_text: str) -> bool:
    """Detect user intent to ask for provenance / trace status.

    This must have higher priority than memory capability/governance classifiers.
    """

    t = (user_text or "").strip().lower()
    if not t:
        return False

    # Strong triggers (BHS + EN)
    if re.search(
        r"(?i)\b("
        r"provenance|sources\s+used|status\s+izvora|"
        r"izvor|izvori|izvori\s+znanja|"
        r"odakle\s+ti(\s+info|\s+ovo)?|odakle\s+podaci|"
        r"na\s+osnovu\s+\u010dega|na\s+osnovu\s+cega|"
        r"sta\s+je\s+koristen\w*|\u0161ta\s+je\s+kori\u0161ten\w*|"
        r"sta\s+je\s+preskocen\w*|\u0161ta\s+je\s+presko\u010den\w*|"
        r"za\u0161to\s+presko\u010den\w*|zasto\s+preskocen\w*|"
        r"trace"
        r")\b",
        t,
    ):
        return True

    # Source-list phrasing like "KB/Identity/Memory/Notion"
    if "kb" in t and "identity" in t and "notion" in t and "memory" in t:
        return True

    return False


def _build_trace_status_text(*, trace_v2: Dict[str, Any], english_output: bool) -> str:
    used = trace_v2.get("used_sources")
    used_list = [
        str(x).strip() for x in (used or []) if isinstance(x, str) and str(x).strip()
    ]

    skipped_list = []
    not_used = trace_v2.get("not_used")
    if isinstance(not_used, list):
        for it in not_used:
            if not isinstance(it, dict):
                continue
            src = it.get("source")
            reason = it.get("skipped_reason")
            if isinstance(src, str) and src.strip():
                if isinstance(reason, str) and reason.strip():
                    skipped_list.append(f"{src.strip()} ({reason.strip()})")
                else:
                    skipped_list.append(f"{src.strip()}")

    if english_output:
        used_txt = ", ".join(used_list) if used_list else "(none)"
        skipped_txt = ", ".join(skipped_list) if skipped_list else "(none)"
        return f"Used: {used_txt}. Skipped: {skipped_txt}."

    used_txt = ", ".join(used_list) if used_list else "(nema)"
    skipped_txt = ", ".join(skipped_list) if skipped_list else "(nema)"
    return f"Korišteno: {used_txt}. Preskočeno: {skipped_txt}."


def _trace_no_sources_text(*, english_output: bool) -> str:
    if english_output:
        return (
            "This answer is based on your input + my analysis (no KB/SSOT sources were used). "
            "If you want this to become system knowledge, write: 'Expand knowledge: ...' (approval-gated)."
        )
    return (
        "Ovo je iz tvog inputa + moje analize (bez KB/SSOT izvora). "
        "Ako želiš da ovo postane znanje sistema, napiši: 'Proširi znanje: ...' (approval-gated)."
    )


def _is_agent_registry_question(user_text: str) -> bool:
    """Detect deterministic intent: user asks to list available agents.

    This must short-circuit *before* any LLM/KB/offline fallback paths.
    """

    t = (user_text or "").strip().lower()
    if not t:
        return False

    # Must mention agents.
    if not re.search(r"(?i)\b(agent|agenti|agente|agentima|agents)\b", t):
        return False

    # Common list/enumeration phrasing (BHS + EN).
    if re.search(
        r"(?i)\b(koje|koji|kakv\w*|lista|spisak|popis|nabroj|dostupn\w*|imamo|available|list|which|what)\b",
        t,
    ):
        return True

    # Registry phrasing.
    if re.search(r"(?i)\bagent\s+registry\b|\bregistry\b.*\bagents?\b", t):
        return True

    return False


def _render_agent_registry_text(*, english_output: bool) -> str:
    try:
        from services.agent_registry_service import AgentRegistryService  # noqa: PLC0415

        reg = AgentRegistryService()
        reg.load_from_agents_json("config/agents.json", clear=True)
        all_agents = reg.list_agents(enabled_only=False)
    except Exception as exc:
        err = (
            str(exc or "agents_registry_unavailable").strip()
            or "agents_registry_unavailable"
        )
        if english_output:
            return (
                "Agent registry is not available in this environment. " f"Detail: {err}"
            )
        return "Agent registry nije dostupan u ovom okruženju. " f"Detalj: {err}"

    enabled = [a for a in all_agents if getattr(a, "enabled", False) is True]
    disabled = [a for a in all_agents if getattr(a, "enabled", False) is False]

    def _fmt(entries: List[Any]) -> List[str]:
        out: List[str] = []
        for a in entries:
            aid = str(getattr(a, "id", "")).strip()
            name = str(getattr(a, "name", "") or aid).strip() or aid
            if not aid:
                continue
            out.append(f"- {name} (agent_id: {aid})")
        return out

    lines: List[str] = []
    if english_output:
        lines.append("Enabled agents:")
        lines.extend(_fmt(enabled) or ["(none)"])
        if disabled:
            lines.append("")
            lines.append("Disabled agents:")
            lines.extend(_fmt(disabled))
        lines.append("")
        lines.append("To delegate: 'Send to agent <agent_id>: <task>'.")
        return "\n".join(lines).strip()

    lines.append("Aktivni agenti:")
    lines.extend(_fmt(enabled) or ["(nema)"])
    if disabled:
        lines.append("")
        lines.append("Onemogućeni agenti:")
        lines.extend(_fmt(disabled))
    lines.append("")
    lines.append("Za delegaciju: 'Pošalji agentu <agent_id>: <zadatak>'.")
    return "\n".join(lines).strip()


def _extract_after_colon(user_text: str) -> str:
    s = (user_text or "").strip()
    if not s:
        return ""
    if ":" in s:
        after = s.split(":", 1)[1].strip()
        return after
    return ""


def _memory_capability_text(*, english_output: bool) -> str:
    if english_output:
        return (
            "Yes, but only through explicit, approval-gated proposals. "
            "No silent writes. In read-only chat I can propose a memory update, "
            "and you approve it before anything is persisted.\n\n"
            "If you want me to remember something, write: 'Remember this: ...' or 'Expand knowledge: ...'\n"
            "(Both create a proposal that requires approval.)\n\n"
            "[KB:memory_model_001] [ID:identity_pack.kernel.system_safety]"
        )
    return (
        "Mogu, ali samo kroz eksplicitne, approval-gated prijedloge. "
        "Nema silent write-a. U read-only chatu mogu pripremiti prijedlog za upis u memoriju/znanje, "
        "a ti ga odobriš prije nego što se bilo šta trajno sačuva.\n\n"
        "Ako želiš da nešto zapamtim, napiši: 'Zapamti ovo: ...' ili 'Proširi znanje: ...' "
        "(oba prave proposal koji traži odobrenje).\n\n"
        "[KB:memory_model_001] [ID:identity_pack.kernel.system_safety]"
    )


def _normalize_item_text(text: str) -> str:
    s = (text or "").strip()
    if not s:
        return ""
    # Normalize whitespace only (deterministic; preserves content).
    return re.sub(r"\s+", " ", s)


def _deterministic_memory_item_type(full_prompt: str) -> str:
    t = (full_prompt or "").strip().lower()
    if t.startswith("proširi znanje") or t.startswith("prosiri znanje"):
        return "rule"
    if t.startswith("nauči") or t.startswith("nauci"):
        return "fact"
    if t.startswith("zapamti") or t.startswith("remember"):
        # Heuristic but deterministic: preferences often use "moj/my".
        if " moj " in f" {t} " or " my " in f" {t} ":
            return "preference"
        return "fact"
    return "fact"


def _memory_idempotency_key(
    *, item_type: str, item_text: str, tags: List[str], source: str
) -> str:
    tags_norm = [str(x).strip().lower() for x in (tags or []) if str(x).strip()]
    tags_norm = sorted(set(tags_norm))
    payload = {
        "schema_version": "memory_write.v1",
        "item": {
            "type": str(item_type or "").strip().lower() or "fact",
            "text": str(item_text or "").strip(),
            "tags": tags_norm,
            "source": str(source or "").strip().lower() or "user",
        },
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _unknown_mode_text(*, english_output: bool) -> str:
    if english_output:
        return (
            "I don't have this knowledge yet (not in my curated KB / current snapshot).\n\n"
            "Options:\n"
            "1) Clarify: answer 1–3 questions and I'll respond with a best-effort answer (clearly marking assumptions).\n"
            "2) Expand knowledge: write 'Expand knowledge: ...' and I'll prepare an approval-gated write proposal.\n\n"
            "Quick questions:\n"
            "- What is the goal: definition, decision, or implementation plan?\n"
            "- What context/domain is this in (business/tech/legal)?\n"
            "- Any constraints (time, tools, scope)?"
        )
    return (
        "Trenutno nemam to znanje (nije u kuriranom KB-u / trenutnom snapshotu).\n\n"
        "Opcije:\n"
        "1) Razjasni: odgovori na 1–3 pitanja i daću najbolji mogući odgovor (jasno ću označiti pretpostavke).\n"
        "2) Proširi znanje: napiši 'Proširi znanje: ...' i pripremiću approval-gated prijedlog za upis.\n\n"
        "Brza pitanja:\n"
        "- Šta ti tačno treba: definicija, odluka ili plan implementacije?\n"
        "- Koji je kontekst/domena (biz/tech/legal)?\n"
        "- Koja su ograničenja (vrijeme, alati, scope)?"
    )


def _assistant_identity_text(*, english_output: bool) -> str:
    if english_output:
        return (
            "I'm the CEO Advisor in this workspace. I help you think, plan, and execute safely.\n\n"
            "How I work:\n"
            "- READ-only by default: I can analyze, summarize, and propose next steps.\n"
            "- Action is approval-gated: when you want me to change things (e.g., Notion/tasks/DB), I return a proposal you approve.\n"
            "- If knowledge sources (KB/snapshot) are unavailable, I'll say so and stay deterministic/offline-safe.\n\n"
            "How to ask:\n"
            "- For a plan: tell me goal + deadline + constraints.\n"
            "- For execution: say explicitly what to create/update, and I will draft an approval-gated proposal."
        )
    return (
        "Ja sam CEO Advisor u ovom workspace-u. Pomažem ti da razmišljaš, planiraš i izvršiš stvari na siguran način.\n\n"
        "Kako radim:\n"
        "- READ-only po defaultu: mogu analizirati, sažeti i predložiti naredne korake.\n"
        "- Akcije su approval-gated: kad želiš da nešto mijenjam (npr. Notion/taskovi/DB), vratim prijedlog koji ti odobriš.\n"
        "- Ako izvori znanja (KB/snapshot) nisu dostupni, to ću reći i ostajem determinističan/offline-safe.\n\n"
        "Kako da pitaš:\n"
        "- Za plan: reci cilj + rok + ograničenja.\n"
        "- Za izvršenje: eksplicitno napiši šta da kreiram/izmijenim i pripremiću approval-gated prijedlog."
    )


def _assistant_memory_text(*, english_output: bool) -> str:
    if english_output:
        return (
            "I have two kinds of memory:\n"
            "- Short-term: I keep the context of the current conversation while the session lasts.\n"
            "- Long-term (only with approval): I can write facts to Notion/KB via an approval-gated process.\n"
            "- I do not store anything implicitly, and I never write changes autonomously without your approval.\n"
            "- WRITE (Notion) is strictly propose → approve → execute."
        )
    return (
        "Imam dvije vrste pamćenja:\n"
        "- Kratkoročno: pamtim kontekst tekućeg razgovora dok traje sesija.\n"
        "- Dugoročno (samo uz odobrenje): mogu upisati činjenice u Notion/KB kroz approval-gated proces.\n"
        "- Ne pamtim ništa implicitno niti samostalno upisujem promjene bez tvog odobrenja.\n"
        "- WRITE (Notion) ide isključivo kroz propose → approve → execute."
    )


def _should_use_kickoff_in_offline_mode(user_text: str) -> bool:
    t0 = (user_text or "").strip().lower()
    if not t0:
        return False

    # Normalize BHS diacritics so sedmični -> sedmicni (matches sedmic*).
    t = (
        t0.replace("č", "c")
        .replace("ć", "c")
        .replace("š", "s")
        .replace("đ", "dj")
        .replace("ž", "z")
    )
    # If user is asking about goals/tasks/KPIs/planning in an empty state,
    # the deterministic kickoff is a good enterprise-safe fallback.
    # IMPORTANT: don't trigger dashboard/kickoff purely on the word "plan".
    # Otherwise normal questions like "biznis plan" get wrongly routed to GOALS/TASKS.
    # NOTE (enterprise safety): only explicit action commands should trigger kickoff
    # via goal/task targeting; narrative mentions must stay read-only.
    ok, kind = _has_explicit_action_for_goal_task(t)
    wants_targets = bool(ok and kind in {"goal", "task"})

    # Planning kickoff is allowed ONLY for explicit weekly/sedmic* signals.
    wants_planning = bool(re.search(r"(?i)\b(weekly|sedmic\w*)\b", t))

    return wants_planning or wants_targets


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


def _is_assistant_role_or_capabilities_question(user_text: str) -> bool:
    """True for meta questions about the assistant itself.

    These should NOT trigger the empty-tasks weekly priorities auto-draft.
    """

    t = (user_text or "").strip().lower()
    if not t:
        return False

    return bool(
        re.search(
            r"(?i)\b("
            r"koja\s+je\s+tvoja\s+uloga|"
            r"ko\s+si|"
            r"\u0161ta\s+si|sta\s+si|"
            r"\u0161ta\s+mo\u017ee\u0161|sta\s+mozes|"
            r"\u0161ta\s+radi\u0161|sta\s+radis|"
            r"kako\s+mi\s+najbolje\s+mozes\s+pomo[\u0107c]|"
            r"what\s+is\s+your\s+role|what\s+can\s+you\s+do|how\s+can\s+you\s+help"
            r")\b",
            t,
        )
    )


def _is_assistant_memory_meta_question(user_text: str) -> bool:
    """True for meta questions about the assistant's memory/capability to remember.

    These must never fall into unknown-mode, even when general knowledge is disabled.
    """

    t0 = (user_text or "").strip().lower()
    if not t0:
        return False

    # Normalize BHS diacritics so pamćenje -> pamcenje, pamtiš -> pamtis.
    t = (
        t0.replace("č", "c")
        .replace("ć", "c")
        .replace("š", "s")
        .replace("đ", "dj")
        .replace("ž", "z")
    )

    # Guard: do NOT hijack explicit memory write / storage requests.
    if re.search(
        r"(?i)\b(zapamt\w*|upis\w*|snim\w*|store\s+this|remember\s+this|save\s+this|memor(y|ija)\s+write)\b",
        t,
    ):
        return False

    # Keep scope tight: only match assistant/self-memory meta questions.
    return bool(
        re.search(
            r"(?i)\b("
            r"(da\s*li\s+)?(ti\s+)?imas\s+pamcenje|"
            r"(da\s*li\s+)?imas\s+li\s+pamcenje|"
            r"(da\s*li\s+)?(ti\s+)?pamtis|"
            r"kako\s+pamtis|"
            r"sta\s+pamtis|"
            r"kakvo\s+pamcenje\s+imas|"
            r"(da\s*li\s+)?(ti\s+)?imas\s+memoriju|"
            r"do\s+you\s+have\s+memory|"
            r"do\s+you\s+remember|"
            r"how\s+do\s+you\s+remember"
            r")\b",
            t,
        )
    )


def _is_planning_or_help_request(user_text: str) -> bool:
    """True for advisory 'help me plan/start' prompts.

    These should NOT be forced into dashboard GOALS/TASKS format.
    """

    t = (user_text or "").strip().lower()
    if not t:
        return False
    if _is_assistant_role_or_capabilities_question(t):
        return False
    return bool(
        re.search(
            r"(?i)\b("
            r"planiram|planir\w*|sljede\w*\s+sedmic\w*|naredn\w*\s+sedmic\w*|"
            r"mo\u017ee\u0161\s+li\s+mi\s+pomo\u0107|mozes\s+li\s+mi\s+pomo[\u0107c]|"
            r"kako\s+da\s+pocn\w*|kako\s+da\s+po\u010dn\w*|krenut\w*|"
            r"pomozi|pomo\u0107|pomoc|pomo\u0107i|pomoci|help|start|po\u010det\w*|pocet\w*|"
            r"7\s*dana|sedmodnev\w*|7-day|7day"
            r")\b",
            t,
        )
    )


def _is_advisory_thinking_request(user_text: str) -> bool:
    """True for prompts asking for opinion/review/analysis/plan on provided context.

    These should not be hard-blocked by the SSOT/snapshot gate.
    """

    t = (user_text or "").strip().lower()
    if not t:
        return False

    # Avoid misclassifying explicit dashboard/listing requests.
    # NOTE: Do NOT treat "procitaj ovo" style prompts as dashboard listing, even if they mention 'cilj'.
    if re.search(
        r"(?i)\b(pokazi|poka\u017ei|prika\u017ei|prikazi|izlistaj|show|list)\b",
        t,
    ) and re.search(r"(?i)\b(cilj\w*|goal\w*|task\w*|zadat\w*|zadac\w*|kpi\w*)\b", t):
        return False

    thinking_markers = bool(
        re.search(
            r"(?i)\b("
            r"\u0161ta(\s+ti)?\s+misl\w*|sta(\s+ti)?\s+misl\w*|"
            r"misljenj\w*|mi\u0161ljenj\w*|"
            r"feedback|komentar\w*|review|"
            r"procijeni|ocijeni|"
            r"analiz\w*|"
            r"pro\u010ditaj|procitaj|read\s+this|pregledaj"
            r")\b",
            t,
        )
    )

    plan_markers = bool(
        re.search(
            r"(?i)\b("
            r"mo\u017ee\s+li\s+se\s+napraviti\s+plan|"
            r"moze\s+li\s+se\s+napraviti\s+plan|"
            r"napravi\s+plan|make\s+a\s+plan"
            r")\b",
            t,
        )
    )

    return bool(thinking_markers or plan_markers)


def _is_advisory_review_of_provided_content(user_text: str) -> bool:
    """True when the user asks for a review/feedback of their provided text.

    Enterprise intent:
    - This is read-only analysis over user-provided content.
    - It must NOT be blocked by missing KB/SSOT snapshot.
    """

    raw = (user_text or "").strip()
    if not raw:
        return False

    # Long, pasted content strongly indicates user-provided material (even if phrasing is brief).
    long_content = (len(raw) >= 800) or (raw.count("\n") >= 10)

    t = raw.lower()
    markers = bool(
        re.search(
            r"(?i)\b("
            r"pro\u010ditaj|procitaj|pregledaj|review|feedback|"
            r"analiziraj|analiz\w*|"
            r"ocijeni|procijeni|"
            r"komentar\w*|"
            r"\u0161ta(\s+ti)?\s+misl\w*|sta(\s+ti)?\s+misl\w*|"
            r"reci\s+mi\s+\u0161ta\s+misl\w*|reci\s+mi\s+sta\s+misl\w*|"
            r"what\s+do\s+you\s+think|give\s+me\s+feedback"
            r")\b",
            t,
        )
    )

    # If user explicitly requested review OR they pasted a lot of content.
    return bool(markers or long_content)


def _advisory_review_fallback_text(*, english_output: bool) -> str:
    if english_output:
        return (
            "I can review your provided content and give read-only feedback. "
            "I won't claim any internal business state (SSOT) without a snapshot.\n\n"
            "To make the review actionable, I’ll cover:\n"
            "1) Goal & audience (what success looks like)\n"
            "2) Core assumptions and missing inputs\n"
            "3) Structure & clarity (sections, sequencing, redundancy)\n"
            "4) Risks/edge cases and mitigations\n"
            "5) Metrics/KPIs and next-step checklist\n\n"
            "If you want, paste the text (or keep it as-is if you already did) and tell me: "
            "target audience + deadline + constraints."
        )
    return (
        "Mogu pročitati tvoj tekst i dati READ-ONLY feedback / analizu. "
        "Neću tvrditi interno poslovno stanje (SSOT) bez snapshot-a.\n\n"
        "Da review bude koristan, pokriću:\n"
        "1) Cilj i publiku (šta znači uspjeh)\n"
        "2) Pretpostavke i šta nedostaje\n"
        "3) Strukturu i jasnoću (sekcije, tok, ponavljanja)\n"
        "4) Rizike i mitigacije\n"
        "5) KPI-je i checklistu sljedećih koraka\n\n"
        "Ako želiš preciznije, napiši još: ciljna publika + rok + ograničenja."
    )


def _advisory_no_snapshot_safe_analysis_text(*, english_output: bool) -> str:
    """Safe, read-only coaching/analysis template when SSOT snapshot is missing.

    Must not claim internal business state and must not instruct execution.
    """

    if english_output:
        return (
            "I can’t confirm internal business status without your internal data, but I can review your text and propose a safe structure.\n\n"
            "Goal\n"
            "- Define the outcome (what changes), the deadline, and the success metric\n\n"
            "Offer\n"
            "- What’s the core offer, who it’s for, and what proof you have\n\n"
            "Channels\n"
            "- 1–2 primary channels and a simple cadence\n\n"
            "Script\n"
            "- Opening → qualification → pitch → objection handling → next step\n\n"
            "Daily metrics\n"
            "- Activity targets (messages/calls/meetings) + conversion checkpoints\n\n"
            "10/30/60/90\n"
            "- 10 days: pipeline + quick wins\n"
            "- 30 days: standardize messaging + process\n"
            "- 60 days: retention/follow-up system\n"
            "- 90 days: scale channels + automate reporting\n\n"
            "Risks & mitigations\n"
            "- Too broad → narrow the offer\n"
            "- Low activity → non-negotiable daily inputs\n"
            "- Weak follow-up → explicit follow-up windows (24h/72h/7d)\n\n"
            "Next steps\n"
            "1) Paste the text (or confirm it’s complete)\n"
            "2) Tell me: audience + deadline + constraints\n"
            "3) I’ll return: critique + improvements + a tightened 1-page version"
        )

    return (
        "Ne mogu potvrditi ‘stanje/status’ kao činjenicu bez tvojih internih podataka, ali mogu pročitati tvoj tekst i dati READ-ONLY feedback i predložiti sigurnu strukturu.\n\n"
        "Cilj\n"
        "- Definiši ishod, rok i mjeru uspjeha (1 KPI)\n\n"
        "Ponuda\n"
        "- Šta tačno nudiš, kome, i koji je dokaz/benefit\n\n"
        "Kanali\n"
        "- 1–2 primarna kanala + jednostavna dnevna rutina\n\n"
        "Skripta\n"
        "- Otvaranje → kvalifikacija → pitch → objekcije → sljedeći korak\n\n"
        "Dnevne metrike\n"
        "- Dnevni inputi (poruke/pozivi/sastanci) + checkpointi konverzije\n\n"
        "Prioriteti\n"
        "- 1–3 stvari koje moraju biti tačne ovaj tjedan (npr. sužavanje opsega, definicija deliverable-a, dogovor oko promjena)\n\n"
        "Pitanja\n"
        "- Šta je ‘must-have’ vs ‘nice-to-have’? Ko odobrava promjene? Koji je dnevni limit vremena po developeru?\n\n"
        "Plan (sljedeća sedmica)\n"
        "- Dnevno: fokus + 1 deliverable + 1 checkpoint; kraj sedmice: demo + odluka o scope-u\n\n"
        "10/30/60/90\n"
        "- 10 dana: pipeline + brzi rezultati\n"
        "- 30 dana: standardizuj poruku + proces\n"
        "- 60 dana: follow-up sistem + rutina\n"
        "- 90 dana: skaliranje kanala + reporting\n\n"
        "Rizici i mitigacije\n"
        "- Preširoko → suzi ponudu\n"
        "- Premalo aktivnosti → uvedi ‘non-negotiable’ dnevne inpute\n"
        "- Slab follow-up → follow-up prozor 24h/72h/7d\n\n"
        "Next steps\n"
        "1) Zalijepi tekst (ili potvrdi da je kompletan)\n"
        "2) Napiši: publika + rok + ograničenja\n"
        "3) Ja vraćam: kritiku + poboljšanja + zategnutu 1-page verziju"
    )


def _strip_internal_contract_leaks(text: str) -> str:
    """Remove internal schema/prompt artifacts from user-facing text.

    The model may echo/paraphrase contract instructions (e.g. Required keys/text/proposed_commands).
    These must never appear in enterprise user-facing output.
    """

    t = text if isinstance(text, str) else ""
    if not t:
        return ""

    lowered = t.lower()
    markers = (
        "required keys",
        "proposed_commands",
        "return only valid json",
        "json object",
        "do not wrap the json",
        "tačno dva ključa",
        "tacno dva kljuca",
        "ključa",
        "kljuca",
        '"text"',
        '"proposed_commands"',
    )

    if not any(m in lowered for m in markers):
        return t

    # Drop any line that looks like internal output-contract instructions.
    out_lines: List[str] = []
    for line in t.splitlines():
        ln = line.strip()
        lnl = ln.lower()
        if not ln:
            out_lines.append(line)
            continue
        if any(m in lnl for m in markers):
            continue
        out_lines.append(line)

    cleaned = "\n".join(out_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned


def _is_revenue_growth_deliverable_request(user_text: str) -> bool:
    """True for concrete sales/growth deliverables (messages/emails/sequences/scripts).

    This is used to prevent the empty-TASKS weekly priorities fallback from hijacking
    deliverable drafting requests (e.g. follow-up poruke, cold email sekvence).
    """

    t = (user_text or "").strip().lower()
    if not t:
        return False

    # If user is explicitly asking for weekly/7-day planning, this is not a deliverable.
    if re.search(r"(?i)\b(weekly|sedmic\w*|7\s*dana|7-day|7day)\b", t):
        return False

    # Require at least one concrete deliverable keyword.
    return bool(
        re.search(
            r"(?i)\b("
            r"follow\s*-?up|followup|"
            r"cold\s*email|"
            r"email|e-mail|mail|"
            r"dm|direct\s+message|"
            r"poruk\w*|msg|message\w*|"
            r"outreach|prospect\w*|lead\w*|"
            r"sekvenc\w*|sequence\w*|"
            r"skript\w*|script\w*|"
            r"pitch|ponud\w*|proposal\w*|"
            r"linkedin|"
            r"funnel|pipeline|sales"
            r")\b",
            t,
        )
    )


def _is_dashboard_intent(user_text: str) -> bool:
    """True only for explicit dashboard/listing/status intent.

    Note: merely mentioning 'goal/task' is not enough.
    """

    t = (user_text or "").strip().lower()
    if not t:
        return False

    if _is_show_request(t):
        return True

    wants_targets = bool(
        re.search(r"(?i)\b(cilj\w*|goal\w*|task\w*|zadat\w*|zadac\w*|kpi\w*)\b", t)
    )
    if not wants_targets:
        return False

    return any(
        k in t
        for k in (
            "dashboard",
            "snapshot",
            "status",
            "stanje",
            "sažetak",
            "sazetak",
            "prioritet",
            "priority",
            "top 3",
            "top3",
            "top 5",
            "top5",
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

    # KPI/finance terms are assumed to be business-fact sensitive in CEO context.
    # Without SSOT snapshot, we must not assert values or status.
    kpi_terms = (
        "revenue",
        "prihod",
        "mrr",
        "arr",
        "profit",
        "dobit",
        "margin",
        "marža",
        "ebitda",
        "cash",
        "gotovina",
        "burn",
        "runway",
        "churn",
        "ltv",
        "cac",
        "gmv",
        "arpu",
    )
    if any(s in t for s in kpi_terms):
        return True

    # "status/stanje" questions become fact-sensitive when tied to goals/tasks/KPIs.
    wants_status = bool(re.search(r"(?i)\b(status|stanje|progress|napredak)\b", t))
    wants_target = bool(
        re.search(
            r"(?i)\b(cilj\w*|goal\w*|task\w*|zadat\w*|zadac\w*|kpi\w*|project\w*|projekat\w*|revenue|prihod|profit|dobit|margin|marža|ebitda)\b",
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

    # Planning/help prompts should NOT be forced into dashboard (GOALS/TASKS) format.
    if _is_planning_or_help_request(t):
        return False

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

    # Structured dashboard mode is ONLY for explicit dashboard intent.
    return _is_dashboard_intent(t)

    return False


def _is_show_request(user_text: str) -> bool:
    t = (user_text or "").strip().lower()
    if not t:
        return False
    show = bool(
        re.search(
            r"(?i)\b(pokazi|poka\u017ei|prika\u017ei|prikazi|izlistaj|show|list|pogledaj)\b",
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

    # ISO already
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s

    # dd.mm.yyyy
    m = re.fullmatch(r"(\d{2})\.(\d{2})\.(\d{4})", s)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        if len(yyyy) == 4:
            return f"{yyyy}-{mm}-{dd}"

    return None


def _extract_deadline_from_text(text: str) -> Optional[str]:
    """Finds deadline/due date in the user's message.

    Supports:
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

    # Normalize payload lists to avoid null semantics in consumers (e.g. PowerShell).
    payload_norm: Dict[str, Any] = (
        snapshot_payload if isinstance(snapshot_payload, dict) else {}
    )
    payload_norm = dict(payload_norm)
    for k in ("goals", "tasks", "projects"):
        if not isinstance(payload_norm.get(k), list):
            payload_norm[k] = []

    ready_raw = None
    try:
        v = raw_snapshot.get("ready") if isinstance(raw_snapshot, dict) else None
        if isinstance(v, bool):
            ready_raw = v
        elif v is not None:
            ready_raw = bool(v)
    except Exception:
        ready_raw = None

    if ready_raw is None:
        # If snapshot wrapper exists, treat it as ready (even if lists are empty).
        ready_raw = bool(raw_snapshot)

    out: Dict[str, Any] = {
        "present_in_request": bool(raw_snapshot),
        "available": bool(available is True),
        "ready": bool(ready_raw is True),
        "payload": payload_norm,
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


def _empty_tasks_fallback_output(
    *,
    base_text: str,
    goals: Any,
    projects: Any,
    memory_snapshot: Any,
    conversation_state: Any,
    english_output: bool,
    snap_trace: Dict[str, Any],
) -> AgentOutput:
    def _safe_list(x: Any) -> List[Dict[str, Any]]:
        if isinstance(x, list):
            return [i for i in x if isinstance(i, dict)]
        return []

    def _title(it: Dict[str, Any]) -> str:
        for k in ("title", "name", "Name"):
            v = it.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return ""

    def _time_key(it: Dict[str, Any]) -> str:
        v = it.get("last_edited_time")
        return v.strip() if isinstance(v, str) else ""

    g = _safe_list(goals)
    p = _safe_list(projects)

    items: List[Dict[str, Any]] = []
    for it in p:
        t = _title(it)
        if t:
            items.append({"kind": "project", "title": t, "t": _time_key(it)})
    for it in g:
        t = _title(it)
        if t:
            items.append({"kind": "goal", "title": t, "t": _time_key(it)})

    active_decision_title = ""
    if isinstance(memory_snapshot, dict):
        ad = memory_snapshot.get("active_decision")
        if isinstance(ad, dict):
            v = ad.get("title") or ad.get("name")
            if isinstance(v, str) and v.strip():
                active_decision_title = v.strip()

    if not items and not active_decision_title:
        txt = (
            "Nemam dovoljno signala u goals/projects/memory/snapshot da bih dao sedmične prioritete. "
            "TASKS snapshot je prazan, a nemam ni ciljeve/projekte ili aktivnu odluku. "
            "Predlog: uradi 'refresh snapshot' ili mi reci 12 konkretna fokusa za sedmicu."
            if not english_output
            else "I don't have enough signals in goals/projects/memory/snapshot to produce weekly priorities. "
            "TASKS snapshot is empty and there are no goals/projects or active decision context. "
            "Suggestion: refresh snapshot or tell me 12 concrete weekly focuses."
        )
        return AgentOutput(
            text=txt,
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={
                "deterministic": True,
                "intent": "empty_tasks_fallback_refusal",
                "exit_reason": "refusal.insufficient_signals",
                "snapshot": snap_trace,
                "signals": {
                    "goals": len(g),
                    "projects": len(p),
                    "active_decision_title": bool(active_decision_title),
                    "conversation_state_present": bool(
                        isinstance(conversation_state, str)
                        and conversation_state.strip()
                    ),
                },
            },
        )

    items.sort(key=lambda x: (x.get("t") or "", x.get("title") or ""), reverse=True)

    priorities: List[str] = []
    if active_decision_title:
        priorities.append(active_decision_title)
    for it in items:
        t = it.get("title")
        if isinstance(t, str) and t.strip() and t.strip() not in priorities:
            priorities.append(t.strip())
        if len(priorities) >= 3:
            break

    priorities = priorities[:3]
    while len(priorities) < 3:
        priorities.append("(needs input)")

    if english_output:
        header = "TASKS snapshot is empty. Based on goals/projects (and memory when available), here are 3 weekly priorities:\n"
        next_step_label = "Next step"
        goal_title = f"Weekly focus: {priorities[0] if priorities[0] != '(needs input)' else 'Planning'}"
    else:
        header = "TASKS snapshot je prazan. Na osnovu goals/projects (i memory gdje postoji signal), evo 3 sedmična prioriteta:\n"
        next_step_label = "Sljedeći korak"
        goal_title = f"Sedmični fokus: {priorities[0] if priorities[0] != '(needs input)' else 'Planiranje'}"

    lines: List[str] = [header.strip(), ""]
    for i, pr in enumerate(priorities, 1):
        if pr == "(needs input)":
            ns = "Potrebno: napiši 1 rečenicu šta znači uspjeh za ovaj fokus."
            if english_output:
                ns = "Needed: one sentence on what success means for this focus."
        else:
            ns = (
                "Napiši 3-5 bullet-a: scope, vlasnik, prvi deliverable."
                if not english_output
                else "Write 35 bullets: scope, owner, first deliverable."
            )
        lines.append(f"{i}) {pr}")
        lines.append(f"   {next_step_label}: {ns}")
        lines.append("")

    ops: List[Dict[str, Any]] = []
    goal_desc = (
        "Auto-draft jer je TASKS snapshot prazan. Izvor: goals/projects snapshot (+ memory signal ako postoji)."
        if not english_output
        else "Auto-draft because TASKS snapshot is empty. Source: goals/projects snapshot (+ memory signal if present)."
    )
    ops.append(
        {
            "op_id": "goal_1",
            "intent": "create_goal",
            "payload": {
                "title": goal_title,
                "description": goal_desc,
                "priority": "high",
                "status": "pending",
            },
        }
    )

    for i, pr in enumerate(priorities[:3], 1):
        title = f"Next action  {pr}" if english_output else f"Sljedeća akcija  {pr}"
        desc = (
            "Draft task (approval-gated). Define the first deliverable and owner."
            if english_output
            else "Draft task (traži odobrenje). Definiši prvi deliverable i vlasnika."
        )
        ops.append(
            {
                "op_id": f"task_{i}",
                "intent": "create_task",
                "payload": {
                    "title": title,
                    "description": desc,
                    "priority": "high" if i == 1 else "medium",
                    "status": "pending",
                    "goal_id": "$goal_1",
                },
            }
        )

    proposed = ProposedCommand(
        command="notion_write",
        intent="notion_write",
        args={
            "ai_command": {
                "command": "notion_write",
                "intent": "batch_request",
                "params": {
                    "operations": ops,
                    "source_prompt": "auto_draft_empty_tasks_fallback",
                },
            },
            "draft": {
                "title": goal_title,
                "description": goal_desc,
                "kpi": None,
                "due_date": None,
                "priority": "high",
                "status": "proposed",
                "needs_approval": True,
            },
        },
        reason=(
            "Auto-draft: create 1 goal + 3 tasks (approval required)."
            if english_output
            else "Auto-draft: kreiraj 1 cilj + 3 taska (traži odobrenje)."
        ),
        requires_approval=True,
        risk="LOW",
        dry_run=True,
        scope="api_execute_raw",
        payload_summary={
            "endpoint": "/api/execute/raw",
            "canon": "CEO_CONSOLE_EXECUTION_FLOW",
            "source": "empty_tasks_fallback",
        },
    )

    return AgentOutput(
        text="\n".join(lines).strip(),
        proposed_commands=[proposed],
        agent_id="ceo_advisor",
        read_only=True,
        trace={
            "deterministic": True,
            "intent": "empty_tasks_fallback_priorities",
            "exit_reason": "deterministic.empty_tasks_fallback",
            "snapshot": snap_trace,
            "signals": {
                "goals": len(g),
                "projects": len(p),
                "active_decision_title": bool(active_decision_title),
                "conversation_state_present": bool(
                    isinstance(conversation_state, str) and conversation_state.strip()
                ),
            },
        },
    )


# -------------------------------
# Main agent entrypoint
# -------------------------------
async def create_ceo_advisor_agent(
    agent_input: AgentInput, ctx: Dict[str, Any]
) -> AgentOutput:
    logger = logging.getLogger(__name__)
    logger.warning(
        "[DEBUG] Pozvan je create_ceo_advisor_agent! agent_input=%s", agent_input
    )

    # --- LLM GATE LOGGING ---
    allow_general_raw = os.getenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")
    allow_general = allow_general_raw == "1"

    base_text = (agent_input.message or "").strip()
    if not base_text:
        base_text = "Reci ukratko šta možeš i kako mogu tražiti akciju."

    def _norm_bhs_ascii(text: str) -> str:
        t = (text or "").strip().lower()
        if not t:
            return ""
        return (
            t.replace("č", "c")
            .replace("ć", "c")
            .replace("š", "s")
            .replace("đ", "dj")
            .replace("ž", "z")
        )

    def _is_deliverable_continue(text: str) -> bool:
        # Explicit continuation phrases only (per spec).
        t = _norm_bhs_ascii(text)
        if not t:
            return False
        return bool(
            re.search(
                r"(?i)\b(nastavi|jos|prosiri|dodaj\s+jos|iteriraj)\b",
                t,
            )
        )

    def _deliverable_hash(text: str) -> str:
        s = (text or "").strip()
        if not s:
            return ""
        return _sha256_prefix(s)[:16]

    def _conversation_id() -> Optional[str]:
        cid0 = None
        try:
            cid0 = ctx.get("conversation_id") if isinstance(ctx, dict) else None
        except Exception:
            cid0 = None
        if isinstance(cid0, str) and cid0.strip():
            return cid0.strip()

        cid1 = getattr(agent_input, "conversation_id", None)
        if isinstance(cid1, str) and cid1.strip():
            return cid1.strip()
        return None

    def _mark_deliverable_completed(*, conversation_id: str, task_text: str) -> None:
        try:
            from services.ceo_conversation_state_store import (  # noqa: PLC0415
                ConversationStateStore,
            )

            ConversationStateStore.update_meta(
                conversation_id=conversation_id,
                updates={
                    "deliverable_last_completed": True,
                    "deliverable_last_completed_at": float(time.time()),
                    "deliverable_last_completed_hash": _deliverable_hash(task_text),
                },
            )
        except Exception:
            pass

    def _was_deliverable_completed(*, conversation_id: str, task_text: str) -> bool:
        try:
            from services.ceo_conversation_state_store import (  # noqa: PLC0415
                ConversationStateStore,
            )

            meta = ConversationStateStore.get_meta(conversation_id=conversation_id)
            if not isinstance(meta, dict):
                return False
            h = _deliverable_hash(task_text)
            return bool(h) and (meta.get("deliverable_last_completed_hash") == h)
        except Exception:
            return False

    def _get_pending_deliverable_offer(
        conversation_id: str,
    ) -> Optional[Dict[str, Any]]:
        try:
            from services.ceo_conversation_state_store import (  # noqa: PLC0415
                ConversationStateStore,
            )

            meta = ConversationStateStore.get_meta(conversation_id=conversation_id)
            if not isinstance(meta, dict):
                return None
            v = meta.get("pending_deliverable_offer")
            return v if isinstance(v, dict) else None
        except Exception:
            return None

    def _set_pending_deliverable_offer(
        conversation_id: str, offer: Dict[str, Any]
    ) -> None:
        try:
            from services.ceo_conversation_state_store import (  # noqa: PLC0415
                ConversationStateStore,
            )

            ConversationStateStore.update_meta(
                conversation_id=conversation_id,
                updates={
                    "pending_deliverable_offer": offer,
                    "pending_deliverable_offer_at": float(time.time()),
                },
            )
        except Exception:
            pass

    def _clear_pending_deliverable_offer(conversation_id: str) -> None:
        try:
            from services.ceo_conversation_state_store import (  # noqa: PLC0415
                ConversationStateStore,
            )

            ConversationStateStore.update_meta(
                conversation_id=conversation_id,
                updates={
                    "pending_deliverable_offer": None,
                    "pending_deliverable_offer_at": None,
                },
            )
        except Exception:
            pass

    continue_deliverable = _is_deliverable_continue(base_text)
    intent = classify_intent(base_text)

    def _debug_trace_enabled() -> bool:
        v = (os.getenv("DEBUG_TRACE") or "").strip().lower()
        return v in {"1", "true", "yes", "on"}

    def _is_deliverable_confirm(text: str) -> bool:
        raw = (text or "").strip()
        if not raw:
            return False

        # Defensive: do not treat questions as confirmations.
        if "?" in raw:
            return False

        t = _norm_bhs_ascii(raw)
        t = re.sub(r"[^a-z0-9\s]", " ", t)
        t = " ".join(t.split())

        if not t:
            return False
        if t.startswith("da li ") or t.startswith("da l "):
            return False

        # Never treat a negated message as a confirmation (e.g., "ne zelim").
        if re.search(
            r"(?i)\b(ne|nemoj|necu|ne\s+zelim|odustani|stop|cancel|nije\s+potrebno|ne\s+treba)\b",
            t,
        ):
            return False

        # Minimal, explicit confirmations only.
        # NOTE: Avoid ambiguous tokens like "ok" / "moze" which can appear in normal questions
        # (e.g., "da li mi agent moze pomoci...") and would incorrectly trigger delegation.
        allowed = {
            "da",
            "yes",
            "y",
            "zelim",
            "hocu",
            "uradi to",
            "slazem se",
            "go ahead",
            "proceed",
            "confirm",
            "potvrdi",
        }
        if t in allowed:
            return True

        return bool(
            re.search(
                r"(?i)\b(uradi\s+to|slazem\s+se|proceed|go\s+ahead|potvrdi|confirm|da|zelim|hocu)\b",
                t,
            )
        )

    def _is_deliverable_decline(text: str) -> bool:
        raw = (text or "").strip()
        if not raw:
            return False
        if "?" in raw:
            return False
        t = _norm_bhs_ascii(raw)
        t = re.sub(r"[^a-z0-9\s]", " ", t)
        t = " ".join(t.split())
        if not t:
            return False
        if t.startswith("da li ") or t.startswith("da l "):
            return False

        # Short/noisy declines.
        if t in {
            "ne",
            "no",
            "n",
            "nemoj",
            "odustani",
            "stop",
            "cancel",
            "ne zelim",
            "necu",
            "nije potrebno",
            "ne treba",
            "not now",
            "no thanks",
            "ne hvala",
        }:
            return True

        # Longer declines that include negation.
        return bool(
            re.search(
                r"(?i)\b(ne|nemoj|necu|ne\s+zelim|odustani|stop|cancel|nije\s+potrebno|ne\s+treba)\b",
                t,
            )
        )

    def _is_offer_accept(text: str) -> bool:
        raw = (text or "").strip()
        if not raw:
            return False
        if "?" in raw:
            return False
        t = _norm_bhs_ascii(raw)
        t = re.sub(r"[^a-z0-9\s]", " ", t)
        t = " ".join(t.split())
        if not t:
            return False
        if t.startswith("da li ") or t.startswith("da l "):
            return False

        # More permissive than _is_deliverable_confirm because it is only checked
        # when we have a pending offer marker from the assistant.
        return t in {
            "da",
            "yes",
            "y",
            "ok",
            "okej",
            "moze",
            "zelim",
            "da zelim",
            "zelimo",
            "hocu",
            "uradi",
            "uradi to",
            "slazem se",
        }

    def _deliverable_confirm_prompt_count(*, conversation_id: str) -> int:
        try:
            from services.ceo_conversation_state_store import (  # noqa: PLC0415
                ConversationStateStore,
            )

            meta0 = ConversationStateStore.get_meta(conversation_id=conversation_id)
            if not isinstance(meta0, dict):
                return 0
            v = meta0.get("deliverable_confirm_prompt_count")
            return int(v) if isinstance(v, (int, float)) else 0
        except Exception:
            return 0

    def _deliverable_confirm_prompt_bump(*, conversation_id: str) -> int:
        try:
            from services.ceo_conversation_state_store import (  # noqa: PLC0415
                ConversationStateStore,
            )

            cur = _deliverable_confirm_prompt_count(conversation_id=conversation_id)
            nxt = int(cur) + 1
            ConversationStateStore.update_meta(
                conversation_id=conversation_id,
                updates={
                    "deliverable_confirm_prompt_count": nxt,
                    "deliverable_confirm_prompt_last_at": float(time.time()),
                },
            )
            return nxt
        except Exception:
            return 0

    def _deliverable_confirm_prompt_reset(*, conversation_id: str) -> None:
        try:
            from services.ceo_conversation_state_store import (  # noqa: PLC0415
                ConversationStateStore,
            )

            ConversationStateStore.update_meta(
                conversation_id=conversation_id,
                updates={
                    "deliverable_confirm_prompt_count": 0,
                },
            )
        except Exception:
            return

    def _extract_last_deliverable_from_conversation_state(
        conversation_state: Any,
    ) -> Optional[str]:
        if not isinstance(conversation_state, str) or not conversation_state.strip():
            return None

        # Parse ConversationStateStore summary format:
        #   "N) USER: ..." lines
        user_lines: List[str] = []
        for line in conversation_state.splitlines():
            line = line.strip()
            if "USER:" in line:
                # keep everything after USER:
                try:
                    user_lines.append(line.split("USER:", 1)[1].strip())
                except Exception:
                    continue

        # Choose the most recent user message that is a deliverable intent
        # and is not itself a confirmation.
        for u in reversed(user_lines):
            if _is_deliverable_confirm(u):
                continue
            if classify_intent(u) == "deliverable":
                return u
        return None

    def _has_plan_keywords(text: str) -> bool:
        t = _norm_bhs_ascii(text)
        if not t:
            return False
        return bool(
            re.search(
                r"(?i)\b(plan|prioritet\w*|strateg\w*|roadmap|okvir|korac\w*|korak\w*|timeline|vremensk\w*)\b",
                t,
            )
        )

    def _has_deliverable_markers(text: str) -> bool:
        t = _norm_bhs_ascii(text)
        if not t:
            return False
        return bool(
            re.search(
                r"(?i)\b(email\w*|poruk\w*|message\w*|follow\s*-?up\w*|sekvenc\w*|sequence\w*|dm\b|linkedin\b)\b",
                t,
            )
        )

    def _extract_deadline_hint(text: str) -> Optional[str]:
        raw = (text or "").strip()
        if not raw:
            return None
        t = _norm_bhs_ascii(raw)
        # Simple, bounded capture; we only need a hint for acknowledgement.
        m = re.search(r"(?i)\b(do|until|by)\s+([^\n\r]{1,32})", t)
        if not m:
            return None
        hint = (m.group(0) or "").strip()
        return hint if hint else None

    def _delegation_ack_text(*, user_text: str, english: bool) -> Optional[str]:
        # Must be 1–2 sentences. Prefer paraphrase over verbatim echo.
        raw = (user_text or "").strip()
        if not raw:
            return None
        if not _has_deliverable_markers(raw):
            return None

        deadline = _extract_deadline_hint(raw)
        paraphrase = _truncate(raw, max_chars=90)
        mentions_plan = _has_plan_keywords(raw)

        if english:
            first = (
                "Got it — you're asking for concrete outreach deliverables (messages/emails)."
                + (" You also mentioned a plan." if mentions_plan else "")
            )
            second_parts: List[str] = [f"Request: {paraphrase}."]
            if deadline:
                second_parts.append(f"Deadline hint: {deadline}.")
            second = " ".join(second_parts)
            return " ".join([first, second]).strip()

        first = (
            "Razumijem — tražiš konkretne outreach deliverable-e (poruke/emailove)."
            + (" Pominješ i plan." if mentions_plan else "")
        )
        second_parts_bhs: List[str] = [f"Sažetak: {paraphrase}."]
        if deadline:
            second_parts_bhs.append(f"Rok hint: {deadline}.")
        second = " ".join(second_parts_bhs)
        return " ".join([first, second]).strip()

    def _generic_delegation_ack_text(*, user_text: str, english: bool) -> Optional[str]:
        raw = (user_text or "").strip()
        if not raw:
            return None
        paraphrase = _truncate(raw, max_chars=110)
        deadline = _extract_deadline_hint(raw)
        if english:
            parts: List[str] = [f"Acknowledged. Task summary: {paraphrase}."]
            if deadline:
                parts.append(f"Deadline hint: {deadline}.")
            return " ".join(parts[:2]).strip()
        parts_bhs: List[str] = [f"Razumijem. Sažetak zadatka: {paraphrase}."]
        if deadline:
            parts_bhs.append(f"Rok hint: {deadline}.")
        return " ".join(parts_bhs[:2]).strip()

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

    # -------------------------------
    # Notion Ops ARMED state (SSOT)
    # -------------------------------
    session_id = None
    try:
        for k in ("session_id", "sessionId", "sid"):
            v = meta.get(k)
            if isinstance(v, str) and v.strip():
                session_id = v.strip()
                break
    except Exception:
        session_id = None

    conv_id = getattr(agent_input, "conversation_id", None)
    if not session_id and isinstance(conv_id, str) and conv_id.strip():
        session_id = conv_id.strip()

    notion_ops_state: Dict[str, Any] = {"armed": False, "armed_at": None}
    notion_ops_armed = False
    if isinstance(session_id, str) and session_id.strip():
        try:
            notion_ops_state = await get_notion_ops_state(session_id)
            notion_ops_armed = await notion_ops_is_armed(session_id)
        except Exception:
            notion_ops_state = {"armed": False, "armed_at": None}
            notion_ops_armed = False

    def _sources_trace() -> Tuple[List[str], List[str]]:
        used: List[str] = []
        missing: List[str] = []

        ip0 = getattr(agent_input, "identity_pack", None)
        ip = ip0 if isinstance(ip0, dict) else {}
        if ip:
            used.append("identity_pack")
        else:
            missing.append("identity_pack")

        # Snapshot from request (Notion read snapshot wrapper/payload).
        if isinstance(snapshot_payload, dict) and snapshot_payload:
            used.append("notion_snapshot")
        else:
            missing.append("notion_snapshot")

        gp0 = ctx.get("grounding_pack") if isinstance(ctx, dict) else None
        gp0 = gp0 if isinstance(gp0, dict) else {}

        # KB is considered "present" if the caller provided a kb payload OR a
        # grounding pack includes kb_retrieved, even if entries are empty.
        kb_ctx = ctx.get("kb") if isinstance(ctx, dict) else None
        kb_ctx = kb_ctx if isinstance(kb_ctx, dict) else None
        kb_gp = (
            gp0.get("kb_retrieved")
            if isinstance(gp0.get("kb_retrieved"), dict)
            else None
        )
        if isinstance(kb_ctx, dict) or isinstance(kb_gp, dict):
            used.append("kb")
        else:
            missing.append("kb")

        ms0 = (
            gp0.get("memory_snapshot")
            if isinstance(gp0.get("memory_snapshot"), dict)
            else {}
        )
        mp0 = ms0.get("payload") if isinstance(ms0, dict) else None
        if isinstance(mp0, dict) and mp0:
            used.append("memory")
        else:
            # Some deterministic paths pass memory directly in ctx.
            m1 = ctx.get("memory") if isinstance(ctx, dict) else None
            if isinstance(m1, dict) and m1:
                used.append("memory")
            else:
                missing.append("memory")

        return used, missing

    used_sources, missing_inputs = _sources_trace()

    def _should_gate_proposal(pc: Any) -> bool:
        cmd = str(getattr(pc, "command", None) or "").strip()
        if cmd == "notion_write":
            return True

        if cmd != PROPOSAL_WRAPPER_INTENT:
            return False

        # Memory writes are allowed even when Notion Ops is disarmed.
        intent = getattr(pc, "intent", None)
        if isinstance(intent, str) and intent.strip() == "memory_write":
            return False

        args = getattr(pc, "args", None)
        if isinstance(args, dict):
            if args.get("schema_version") == "memory_write.v1":
                return False

        # Default: wrapper proposals are treated as Notion write intent.
        return True

    def _final(out: AgentOutput) -> AgentOutput:
        # Attach notion ops state consistently.
        try:
            setattr(
                out,
                "notion_ops",
                {
                    "armed": bool(notion_ops_armed is True),
                    "armed_at": notion_ops_state.get("armed_at"),
                    "session_id": session_id,
                    "armed_state": notion_ops_state,
                },
            )
        except Exception:
            pass

        tr = out.trace if isinstance(out.trace, dict) else {}
        tr.setdefault("snapshot", snap_trace)

        # Enforce/merge trace contract fields (last-write-wins, but stable):
        # some upstream layers may already provide used_sources/missing_inputs.
        used_existing = (
            tr.get("used_sources") if isinstance(tr.get("used_sources"), list) else []
        )
        missing_existing = (
            tr.get("missing_inputs")
            if isinstance(tr.get("missing_inputs"), list)
            else []
        )

        used_merged = [
            x
            for x in (used_existing + list(used_sources))
            if isinstance(x, str) and x.strip()
        ]
        missing_merged = [
            x
            for x in (missing_existing + list(missing_inputs))
            if isinstance(x, str) and x.strip()
        ]

        # De-dup while preserving order.
        used_dedup: List[str] = []
        for x in used_merged:
            if x not in used_dedup:
                used_dedup.append(x)

        missing_dedup: List[str] = []
        for x in missing_merged:
            if x not in missing_dedup:
                missing_dedup.append(x)

        # If we consider a source "used", it cannot also be "missing".
        missing_dedup = [x for x in missing_dedup if x not in used_dedup]

        tr["used_sources"] = used_dedup
        tr["missing_inputs"] = missing_dedup
        tr.setdefault(
            "notion_ops",
            {"armed": bool(notion_ops_armed is True), "session_id": session_id},
        )

        # KB trace (required for Responses API debugging): always emit a list.
        kb_ids_used: List[str] = []
        kb_entries_injected = 0
        try:
            gp0 = ctx.get("grounding_pack") if isinstance(ctx, dict) else None
            gp0 = gp0 if isinstance(gp0, dict) else {}

            kb0 = None
            kb_gp = (
                gp0.get("kb_retrieved")
                if isinstance(gp0.get("kb_retrieved"), dict)
                else None
            )
            if isinstance(kb_gp, dict):
                kb0 = kb_gp
            else:
                kb_ctx = ctx.get("kb") if isinstance(ctx, dict) else None
                kb0 = kb_ctx if isinstance(kb_ctx, dict) else None

            if isinstance(kb0, dict):
                kb_entries = kb0.get("entries")
                if isinstance(kb_entries, list):
                    kb_entries_injected = len(kb_entries)
                kb_ids_used = list(kb0.get("used_entry_ids") or [])
        except Exception:
            kb_ids_used = []
            kb_entries_injected = 0

        kb_ids_used = [x for x in kb_ids_used if isinstance(x, str) and x.strip()]
        tr["kb_ids_used"] = kb_ids_used
        tr.setdefault("kb_used_entry_ids", kb_ids_used)
        tr["kb_entries_injected"] = int(kb_entries_injected)

        removed = 0
        if not notion_ops_armed:
            kept: List[ProposedCommand] = []
            for pc in out.proposed_commands or []:
                if _should_gate_proposal(pc):
                    removed += 1
                    continue
                kept.append(pc)
            if removed:
                out.proposed_commands = kept
                tr["notion_ops_gate"] = {
                    "applied": True,
                    "removed_write_proposals": removed,
                    "reason": "notion_ops_disarmed",
                }
                note = "\n\nNotion Ops nije aktiviran — ne vraćam write-proposals. Ako želiš, napiši: 'notion ops aktiviraj'."
                if isinstance(out.text, str) and note.strip() not in out.text:
                    out.text = (out.text or "").rstrip() + note

        # Enterprise safety: never leak internal output-contract instructions.
        try:
            if isinstance(out.text, str) and out.text.strip():
                out.text = _strip_internal_contract_leaks(out.text)
        except Exception:
            pass

        out.trace = tr

        # Persist an explicit deliverable offer marker ONLY when the assistant
        # itself surfaced the offer from KB (business plan template).
        try:
            cid2 = _conversation_id()
            if isinstance(cid2, str) and cid2.strip() and isinstance(out.text, str):
                kb_ids0 = (
                    out.trace.get("kb_ids_used")
                    if isinstance(out.trace, dict)
                    else None
                )
                kb_ids0 = kb_ids0 if isinstance(kb_ids0, list) else []
                kb_ids = [x for x in kb_ids0 if isinstance(x, str) and x.strip()]

                # The offer text lives inside KB:plans_business_plan_001.
                txtn = _norm_bhs_ascii(out.text)
                # Fallback: in tests/offline, kb_ids_used may be empty; however the
                # assistant text may carry an explicit KB marker.
                kb_marker_hit = "kb:plans_business_plan_001" in (out.text or "").lower()
                offer_hit = (
                    ("ako treba" in txtn)
                    and ("mogu dati minimalni" in txtn)
                    and ("template" in txtn)
                    and (("listu pitanja" in txtn) or ("lista pitanja" in txtn))
                    and (("plans_business_plan_001" in kb_ids) or kb_marker_hit)
                )

                if offer_hit:
                    _set_pending_deliverable_offer(
                        cid2.strip(),
                        {
                            "kind": "business_plan_template.v1",
                            "kb_id": "plans_business_plan_001",
                            "source": "kb_offer_sentence",
                        },
                    )
        except Exception:
            pass
        # ------------------------------------------------------------
        # Debug-only observability: prove which intelligence sources were present
        # and whether SSOT snapshot was used as context vs returned.
        # IMPORTANT: This must not affect routing/behavior.
        # ------------------------------------------------------------
        try:
            debug_on = False
            try:
                md0 = (
                    agent_input.metadata if isinstance(agent_input, AgentInput) else {}
                )
                md0 = md0 if isinstance(md0, dict) else {}
                debug_on = bool(md0.get("include_debug"))
            except Exception:
                debug_on = False

            if not debug_on:
                v = (os.getenv("DEBUG_API_RESPONSES") or "").strip().lower()
                debug_on = v in {"1", "true", "yes", "on"}

            if debug_on and isinstance(out.trace, dict):
                gp0 = ctx.get("grounding_pack") if isinstance(ctx, dict) else None
                gp0 = gp0 if isinstance(gp0, dict) else {}

                def _leaf_paths(
                    obj: Any, *, prefix: str = "", max_paths: int = 64
                ) -> List[str]:
                    out_paths: List[str] = []
                    stack: List[Tuple[str, Any, int]] = [(prefix, obj, 0)]
                    while stack and len(out_paths) < max_paths:
                        pfx, cur, depth = stack.pop()
                        if isinstance(cur, dict) and depth < 4:
                            for k in sorted(cur.keys(), reverse=True):
                                if not isinstance(k, str):
                                    continue
                                v = cur.get(k)
                                p2 = f"{pfx}.{k}" if pfx else k
                                stack.append((p2, v, depth + 1))
                            continue
                        if isinstance(cur, list) and depth < 3:
                            # Treat list as leaf; we don't want a huge key explosion.
                            out_paths.append(pfx or prefix or "<list>")
                            continue
                        if pfx:
                            out_paths.append(pfx)
                    return sorted(
                        set([x for x in out_paths if isinstance(x, str) and x.strip()])
                    )

                # identity_used
                ip_gp = (
                    gp0.get("identity_pack")
                    if isinstance(gp0.get("identity_pack"), dict)
                    else {}
                )
                ip_payload = ip_gp.get("payload") if isinstance(ip_gp, dict) else None
                ip_payload = ip_payload if isinstance(ip_payload, dict) else {}

                files_loaded: List[str] = []
                try:
                    meta0 = (
                        ip_payload.get("meta")
                        if isinstance(ip_payload.get("meta"), dict)
                        else {}
                    )
                    lm0 = (
                        meta0.get("last_modified")
                        if isinstance(meta0.get("last_modified"), dict)
                        else {}
                    )
                    for k in (
                        "identity",
                        "kernel",
                        "decision_engine",
                        "static_memory",
                        "memory",
                        "agents",
                    ):
                        if k in lm0 and lm0.get(k) is not None:
                            files_loaded.append(k)
                except Exception:
                    files_loaded = []

                identity_fields_used: List[str] = []
                try:
                    # Focus on /adnan-ai/identity (identity.json) coverage: pack['identity'] subtree.
                    identity_sub = (
                        ip_payload.get("identity")
                        if isinstance(ip_payload.get("identity"), dict)
                        else {}
                    )
                    identity_fields_used = _leaf_paths(
                        identity_sub, prefix="identity", max_paths=64
                    )
                except Exception:
                    identity_fields_used = []

                identity_used = {
                    "files_loaded": files_loaded,
                    "fields_used": identity_fields_used,
                    "hit_count": int(len(identity_fields_used)),
                }

                # ssot_used
                ssot_entities: List[str] = []
                ssot_hit = 0
                try:
                    sp = snapshot_payload if isinstance(snapshot_payload, dict) else {}
                    for k in ("goals", "tasks", "projects", "kpis"):
                        v = sp.get(k)
                        if isinstance(v, list) and v:
                            ssot_entities.append(k)
                            ssot_hit += len([x for x in v if x is not None])
                    # Also count dashboard wrapper as a signal of SSOT availability.
                    if isinstance(sp.get("dashboard"), dict) and sp.get("dashboard"):
                        if "dashboard" not in ssot_entities:
                            ssot_entities.append("dashboard")
                        ssot_hit += 1
                except Exception:
                    ssot_entities = []
                    ssot_hit = 0

                text0 = out.text if isinstance(out.text, str) else ""
                returned = False
                try:
                    if (
                        isinstance(out.trace, dict)
                        and out.trace.get("intent") == "snapshot_read_summary"
                    ):
                        returned = True
                    elif (
                        snapshot_ready
                        and text0.startswith("GOALS (top 3)")
                        and ("TASKS (top 5)" in text0)
                    ):
                        returned = True
                except Exception:
                    returned = False

                ssot_used = {
                    "entities": ssot_entities,
                    "mode": "returned" if returned else "context_only",
                    "hit_count": int(ssot_hit),
                }

                # kb_used
                kb_entry_ids: List[str] = []
                kb_hit = 0
                kb_dbs: List[str] = []
                try:
                    kb_retrieved = (
                        gp0.get("kb_retrieved")
                        if isinstance(gp0.get("kb_retrieved"), dict)
                        else {}
                    )
                    used_ids0 = kb_retrieved.get("used_entry_ids")
                    if isinstance(used_ids0, list):
                        kb_entry_ids = [
                            str(x).strip()
                            for x in used_ids0
                            if isinstance(x, str) and x.strip()
                        ]
                    entries0 = kb_retrieved.get("entries")
                    if isinstance(entries0, list):
                        kb_hit = len([x for x in entries0 if isinstance(x, dict)])
                    kb_snap = (
                        gp0.get("kb_snapshot")
                        if isinstance(gp0.get("kb_snapshot"), dict)
                        else {}
                    )
                    src = kb_snap.get("source")
                    if isinstance(src, str) and src.strip():
                        kb_dbs = [src.strip()]
                except Exception:
                    kb_entry_ids = []
                    kb_hit = 0
                    kb_dbs = []

                kb_used = {
                    "dbs": kb_dbs,
                    "entry_ids": kb_entry_ids,
                    "hit_count": int(kb_hit),
                }

                # memory_used
                mem_keys: List[str] = []
                mem_short = False
                mem_long = False
                mem_hit = 0
                try:
                    ms = (
                        gp0.get("memory_snapshot")
                        if isinstance(gp0.get("memory_snapshot"), dict)
                        else {}
                    )
                    mp = ms.get("payload") if isinstance(ms, dict) else None
                    mp = mp if isinstance(mp, dict) else {}
                    mem_keys = [str(k) for k in sorted(mp.keys()) if isinstance(k, str)]
                    items_count = 0
                    try:
                        items_count = int(mp.get("memory_items_count") or 0)
                    except Exception:
                        items_count = 0
                    mem_long = items_count > 0
                    mem_short = bool(mp.get("active_decision")) or bool(
                        mp.get("decision_outcomes")
                    )
                    mem_hit = items_count
                except Exception:
                    mem_keys = []
                    mem_short = False
                    mem_long = False
                    mem_hit = 0

                memory_used = {
                    "short_term": bool(mem_short),
                    "long_term": bool(mem_long),
                    "keys": mem_keys,
                }

                # prompt_sources: hit-weighted percentages
                total_hits = (
                    int(identity_used["hit_count"])
                    + int(ssot_used["hit_count"])
                    + int(kb_used["hit_count"])
                    + int(mem_hit)
                )
                if total_hits <= 0:
                    prompt_sources = {
                        "identity_pct": 0,
                        "ssot_pct": 0,
                        "kb_pct": 0,
                        "memory_pct": 0,
                    }
                else:
                    prompt_sources = {
                        "identity_pct": int(
                            round(
                                100.0
                                * float(identity_used["hit_count"])
                                / float(total_hits)
                            )
                        ),
                        "ssot_pct": int(
                            round(
                                100.0
                                * float(ssot_used["hit_count"])
                                / float(total_hits)
                            )
                        ),
                        "kb_pct": int(
                            round(
                                100.0 * float(kb_used["hit_count"]) / float(total_hits)
                            )
                        ),
                        "memory_pct": int(
                            round(100.0 * float(mem_hit) / float(total_hits))
                        ),
                    }

                out.trace["identity_used"] = identity_used
                out.trace["ssot_used"] = ssot_used
                out.trace["kb_used"] = kb_used
                out.trace["memory_used"] = memory_used
                out.trace["prompt_sources"] = prompt_sources
        except Exception:
            # Observability must never break the response.
            pass

        # SSOT guard: if snapshot isn't ready/available, do not allow fabricated
        # GOALS/TASKS style tables in the output.
        try:
            txt0 = out.text if isinstance(out.text, str) else ""
            if txt0 and (not snapshot_ready):
                if re.search(r"(?im)^\s*(GOALS|TASKS|CILJEVI|ZADACI)\b", txt0):
                    out.text = (
                        "Nemam SSOT snapshot u ovom trenutku, pa ne mogu pouzdano izlistati ciljeve i zadatke. "
                        "Reci cilj + rok + ograničenja, pa ću napraviti plan."
                        if not english_output
                        else "I don't have the SSOT snapshot right now, so I can't reliably list goals and tasks. "
                        "Tell me the objective + deadline + constraints and I'll draft the plan."
                    )
                    tr.setdefault("ssot_guard", {})
                    tr["ssot_guard"] = {
                        "applied": True,
                        "reason": "snapshot_missing_or_unready",
                    }
                    out.trace = tr
        except Exception:
            pass
        return out

    # Inicijalizacija goals i tasks
    goals, tasks = _extract_goals_tasks(snapshot_payload)

    # LLM gate variables and logging
    propose_only = _is_propose_only_request(base_text)
    use_llm = not propose_only
    fact_sensitive = _is_fact_sensitive_query(base_text)
    snapshot_has_facts = _snapshot_has_business_facts(snapshot_payload)
    advisory_review = _is_advisory_review_of_provided_content(base_text)

    logger.info(
        f"[LLM-GATE] allow_general_raw={allow_general_raw} allow_general={allow_general} (source=env)"
    )
    logger.info(f"[LLM-GATE] use_llm={use_llm} (propose_only={propose_only})")
    logger.info(
        f"[LLM-GATE] fact_sensitive={fact_sensitive} snapshot_has_facts={snapshot_has_facts}"
    )

    llm_configured = _llm_is_configured()
    logger.info(f"[LLM-GATE] _llm_is_configured={llm_configured}")

    snap_trace = _snapshot_trace(
        raw_snapshot=raw_snapshot,
        snapshot_payload=snapshot_payload,
        goals=goals,
        tasks=tasks,
        meta=meta,
    )

    snapshot_ready = bool(
        isinstance(snap_trace, dict) and snap_trace.get("ready") is True
    )

    # Identity/capabilities allowlist: these are meta questions about the assistant.
    # They must never fall into unknown-mode, even when general knowledge is disabled.
    if _is_assistant_role_or_capabilities_question(base_text):
        return _final(
            AgentOutput(
                text=_assistant_identity_text(english_output=english_output),
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace={
                    "deterministic": True,
                    "intent": "assistant_identity",
                    "exit_reason": "deterministic.assistant_identity",
                },
            )
        )

    # Memory/self-knowledge allowlist: meta questions about memory must never hit unknown-mode.
    if _is_assistant_memory_meta_question(base_text):
        return _final(
            AgentOutput(
                text=_assistant_memory_text(english_output=english_output),
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace={
                    "deterministic": True,
                    "intent": "assistant_memory",
                    "exit_reason": "deterministic.assistant_memory",
                },
            )
        )

    # ------------------------------------------------------------
    # Minimal bugfix: YES after explicit business-plan template offer
    # (offer comes from KB:plans_business_plan_001)
    # ------------------------------------------------------------
    cid_offer = _conversation_id()
    pending_offer = (
        _get_pending_deliverable_offer(cid_offer.strip())
        if isinstance(cid_offer, str) and cid_offer.strip()
        else None
    )
    if (
        isinstance(pending_offer, dict)
        and pending_offer.get("kind") == "business_plan_template.v1"
        and isinstance(cid_offer, str)
        and cid_offer.strip()
    ):
        if _is_offer_accept(base_text):
            _clear_pending_deliverable_offer(cid_offer.strip())
            return _final(
                AgentOutput(
                    text=_business_plan_template_with_questions(
                        english_output=bool(english_output)
                    ),
                    proposed_commands=[],
                    agent_id="ceo_advisor",
                    read_only=True,
                    trace={
                        "intent": "business_plan_template_delivered",
                        "snapshot": snap_trace,
                    },
                )
            )

        # User said NO or sent a new request: drop the offer marker and proceed.
        if _is_deliverable_decline(base_text) or (not _is_offer_accept(base_text)):
            _clear_pending_deliverable_offer(cid_offer.strip())

    def _item_title(item: Any) -> Optional[str]:
        if not isinstance(item, dict):
            return None
        for k in ("title", "name", "Name", "Title"):
            v = item.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
        return None

    # READ snapshot must not be coupled to Notion Ops ARMED.
    # If a ready snapshot is present and the user asks about goals/tasks existence,
    # answer deterministically from snapshot instead of disclaiming access.
    if (
        snapshot_ready
        and _wants_notion_task_or_goal(base_text)
        and (not _defers_notion_execution_or_wants_discussion_first(base_text))
    ):
        goals_count = len(goals) if isinstance(goals, list) else 0
        tasks_count = len(tasks) if isinstance(tasks, list) else 0
        g0 = _item_title(goals[0]) if isinstance(goals, list) and goals else None
        t0 = _item_title(tasks[0]) if isinstance(tasks, list) and tasks else None

        parts: list[str] = [
            f"Imam SSOT Notion snapshot (READ): goals={goals_count}, tasks={tasks_count}."
        ]
        if g0:
            parts.append(f"Primjer cilja: {g0}")
        if t0:
            parts.append(f"Primjer taska: {t0}")

        return _final(
            AgentOutput(
                text="\n".join(parts).strip(),
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace={"snapshot": snap_trace, "intent": "snapshot_read_summary"},
            )
        )

    # ---------------------------------------------
    # Explicit delegation request (agent-to-agent)
    # ---------------------------------------------
    def _extract_delegate_target(text: str) -> Optional[str]:
        """Extract a target agent name/id from a user delegation request.

        Supported patterns (BHS/EN, normalized to ASCII):
        - "pos(al)ji agentu <agent>: ..."
        - "delegiraj agentu <agent>: ..."
        """

        t = _norm_bhs_ascii(text)
        if not t:
            return None

        # Pattern A: "pošalji agentu <target> ..."
        m = re.search(
            r"(?i)\b(posalji|delegiraj|proslijedi|prepusti|assign|send)\b\s+\bagent\w*\b\s+(.+)$",
            t,
        )

        # Pattern B: "pošalji <target> agentu ..." (allow punctuation after 'agentu')
        if not m:
            m = re.search(
                r"(?i)\b(posalji|delegiraj|proslijedi|prepusti|assign|send)\b\s+(.+?)\s+\bagent\w*\b(?=\s|$|[:,-])",
                t,
            )
            if not m:
                return None
            raw = (m.group(2) or "").strip()
        else:
            raw = (m.group(2) or "").strip()

        if not raw:
            return None

        # Stop at common separators if they appear later.
        raw = raw.split(":", 1)[0].strip()
        raw = raw.split(",", 1)[0].strip()
        raw = raw.split("-", 1)[0].strip()
        raw = raw.split("—", 1)[0].strip()

        # If the capture starts with a clause starter ("da ..."), then no target was provided.
        raw_norm0 = _norm_bhs_ascii(raw)
        if raw_norm0 in {"da", "to", "please"}:
            return None
        if (
            raw_norm0.startswith("da ")
            or raw_norm0.startswith("da mi ")
            or raw_norm0.startswith("da nam ")
        ):
            return None
        if raw_norm0.startswith("to ") or raw_norm0.startswith("please "):
            return None

        # If the user wrote "pošalji agentu <target> da ...", cut at the clause.
        for sep in (" da ", " to "):
            if sep in raw_norm0:
                raw = raw[: raw_norm0.index(sep)].strip()
                raw_norm0 = _norm_bhs_ascii(raw)
                break

        # If target looks like an agent_id token, keep just the first token.
        first_tok = (raw.split() or [""])[0].strip()
        if (
            first_tok
            and ("_" in first_tok)
            and re.match(r"^[a-z0-9_]+$", _norm_bhs_ascii(first_tok))
        ):
            raw = first_tok

        if not raw:
            return None

        return raw or None

    def _looks_like_delegate_without_target(text: str) -> bool:
        t = _norm_bhs_ascii(text)
        if not t:
            return False
        has_verb = bool(
            re.search(
                r"(?i)\b(posalji|delegiraj|proslijedi|prepusti|assign|send)\b",
                t,
            )
        )
        if not has_verb:
            return False
        # Require the 'agent' noun to avoid catching normal requests like "pošalji email".
        if not re.search(r"(?i)\bagent\w*\b", t):
            return False

        # If we can extract a plausible target, it's not missing-target.
        if _extract_delegate_target(text):
            return False
        return True

    def _enabled_agents_for_picker() -> List[Dict[str, str]]:
        """Return a small list of enabled agents for UI text (id + name)."""
        try:
            from services.agent_registry_service import AgentRegistryService  # noqa: PLC0415

            reg = AgentRegistryService()
            reg.load_from_agents_json("config/agents.json", clear=True)
            enabled = reg.list_agents(enabled_only=True)
        except Exception:
            enabled = []

        out: List[Dict[str, str]] = []
        for e in enabled:
            if not getattr(e, "id", None):
                continue
            # Do not offer delegating back into CEO advisor itself.
            if e.id in {"ceo_advisor", "ceo_clone", "execution_orchestrator"}:
                continue
            out.append({"id": str(e.id), "name": str(e.name or e.id)})

        # Deterministic order: id asc
        out.sort(key=lambda x: x.get("id") or "")
        return out

    def _render_agent_picker(*, english: bool) -> str:
        agents = _enabled_agents_for_picker()
        if not agents:
            return (
                "Nema dostupnih agenata za delegaciju u ovom okruženju."
                if not english
                else "No enabled agents are available for delegation in this environment."
            )

        lines: List[str] = []
        for a in agents[:12]:
            lines.append(f"- {a.get('name')} (agent_id: {a.get('id')})")

        header = (
            "Ko kojem agentu želiš delegirati? Dostupni agenti:"
            if not english
            else "Which agent should I delegate to? Enabled agents:"
        )
        usage = (
            "\n\nPrimjer: 'Pošalji agentu revenue_growth_operator: napiši 3 follow-up poruke.'"
            if not english
            else "\n\nExample: 'Send to agent revenue_growth_operator: draft 3 follow-up messages.'"
        )
        optional = (
            "\n\nOvo je opcija, nije uslov — ako ne želiš delegirati, samo napiši šta tačno treba i ja ću pomoći ovdje."
            if not english
            else "\n\nThis is optional — if you don't want to delegate, just describe what you need and I'll help here."
        )
        return header + "\n" + "\n".join(lines) + usage + optional

    def _resolve_agent_id_from_text(target: str) -> Optional[str]:
        t = _norm_bhs_ascii(target)
        if not t:
            return None

        # Common aliases.
        if t in {"rgo", "revenue growth", "revenue & growth"}:
            return "revenue_growth_operator"
        if "notion" in t:
            return "notion_ops"

        # Fast path: exact id.
        if t in {
            "ceo_advisor",
            "ceo_clone",
            "revenue_growth_operator",
            "notion_ops",
            "execution_orchestrator",
        }:
            return t

        try:
            from services.agent_registry_service import AgentRegistryService  # noqa: PLC0415

            reg = AgentRegistryService()
            reg.load_from_agents_json("config/agents.json", clear=True)
            enabled = reg.list_agents(enabled_only=True)

            # Match by display name containment or keyword hit.
            for e in enabled:
                name_norm = _norm_bhs_ascii(e.name)
                if name_norm and (t == name_norm or t in name_norm):
                    return e.id

                kws = [
                    _norm_bhs_ascii(k)
                    for k in (e.keywords or [])
                    if isinstance(k, str) and k.strip()
                ]
                if t in kws:
                    return e.id
        except Exception:
            return None

        return None

    def _delegation_task_text_from_prompt(prompt_text: str) -> str:
        # Prefer content after the first ':' as the task.
        raw = (prompt_text or "").strip()
        if not raw:
            return ""
        if ":" in raw:
            _, after = raw.split(":", 1)
            after = after.strip()
            return after or raw
        return raw

    def _is_explicit_delegate_to_rgo(text: str) -> bool:
        t = _norm_bhs_ascii(text)
        if not t:
            return False

        mentions_rgo = bool(
            re.search(
                r"(?i)\b(revenue\s*&\s*growth\s*operator\w*|revenue\s+growth\s+operator\w*|rgo)\b",
                t,
            )
        )
        if not mentions_rgo:
            return False

        return bool(
            re.search(
                r"(?i)\b(posalji|delegiraj|proslijedi|prepusti|assign|send)\b",
                t,
            )
        )

    if _is_explicit_delegate_to_rgo(base_text):
        # /api/chat is read-only: never execute delegation here.
        task_text = (base_text or "").strip()
        ack = _generic_delegation_ack_text(
            user_text=task_text,
            english=bool(english_output),
        )
        if not ack:
            return _final(
                AgentOutput(
                    text=(
                        "Koji je tačan zadatak i rok za delegaciju?"
                        if not english_output
                        else "What exactly should I delegate, and what is the deadline?"
                    ),
                    proposed_commands=[],
                    agent_id="ceo_advisor",
                    read_only=True,
                    trace={
                        "intent": "delegate_agent_task",
                        "exit_reason": "delegate_agent_task.missing_task_text",
                        "snapshot": snap_trace,
                    },
                )
            )
        proposed = ProposedCommand(
            command="delegate_agent_task",
            args={
                "agent_id": "revenue_growth_operator",
                "task_text": task_text,
                "endpoint": "/agents/execute",
                "canon": "delegate_agent_task.v1",
            },
            reason="Delegacija Revenue & Growth Operatoru (traži odobrenje).",
            requires_approval=True,
            risk="LOW",
            scope="agents/execute",
            dry_run=True,
            payload_summary={
                "kind": "delegation",
                "command": "delegate_agent_task",
                "payload": {
                    "agent_id": "revenue_growth_operator",
                    "task_text": task_text,
                },
                "endpoint": "/agents/execute",
                "canon": "CEO_CONSOLE_EXECUTION_FLOW",
                "source": "api_chat",
                "confidence_score": 0.7,
                "assumption_count": 0,
                "recommendation_type": "OPERATIONAL",
            },
        )

        out = AgentOutput(
            text=(
                ack
                + "\n\n"
                + (
                    "Želiš li da delegiram ovaj zadatak Revenue & Growth Operatoru?"
                    if not english_output
                    else "Do you want me to delegate this task to Revenue & Growth Operator?"
                )
            ),
            proposed_commands=[proposed],
            agent_id="ceo_advisor",
            read_only=True,
            trace={
                "intent": "delegate_agent_task",
                "delegated_to": "revenue_growth_operator",
                "delegation_reason": "explicit_delegate_request",
                "fallback_used": "none",
                "snapshot": snap_trace,
            },
        )

        return _final(out)

    # Generic: "pošalji/delegiraj agentu <agent>".
    target_txt = _extract_delegate_target(base_text)
    if isinstance(target_txt, str) and target_txt.strip():
        target_id = _resolve_agent_id_from_text(target_txt)
        if isinstance(target_id, str) and target_id.strip():
            # /api/chat is read-only: never execute delegation here.
            task_text = _delegation_task_text_from_prompt(base_text)
            ack = _generic_delegation_ack_text(
                user_text=task_text,
                english=bool(english_output),
            )
            if not ack:
                return _final(
                    AgentOutput(
                        text=(
                            "Koji je tačan zadatak i rok za delegaciju?"
                            if not english_output
                            else "What exactly should I delegate, and what is the deadline?"
                        ),
                        proposed_commands=[],
                        agent_id="ceo_advisor",
                        read_only=True,
                        trace={
                            "intent": "delegate_agent_task",
                            "exit_reason": "delegate_agent_task.missing_task_text",
                            "snapshot": snap_trace,
                        },
                    )
                )
            proposed = ProposedCommand(
                command="delegate_agent_task",
                args={
                    "agent_id": target_id.strip(),
                    "task_text": task_text,
                    "endpoint": "/agents/execute",
                    "canon": "delegate_agent_task.v1",
                },
                reason="Delegacija agentu (traži odobrenje).",
                requires_approval=True,
                risk="LOW",
                scope="agents/execute",
                dry_run=True,
                payload_summary={
                    "kind": "delegation",
                    "command": "delegate_agent_task",
                    "payload": {
                        "agent_id": target_id.strip(),
                        "task_text": task_text,
                    },
                    "endpoint": "/agents/execute",
                    "canon": "CEO_CONSOLE_EXECUTION_FLOW",
                    "source": "api_chat",
                    "confidence_score": 0.7,
                    "assumption_count": 0,
                    "recommendation_type": "OPERATIONAL",
                },
            )

            out = AgentOutput(
                text=(
                    ack
                    + "\n\n"
                    + (
                        f"Želiš li da delegiram ovaj zadatak agentu '{target_id.strip()}'?"
                        if not english_output
                        else f"Do you want me to delegate this task to agent '{target_id.strip()}'?"
                    )
                ),
                proposed_commands=[proposed],
                agent_id="ceo_advisor",
                read_only=True,
                trace={
                    "intent": "delegate_agent_task",
                    "delegated_to": target_id.strip(),
                    "delegation_reason": "explicit_delegate_request",
                    "fallback_used": "none",
                    "snapshot": snap_trace,
                },
            )

            return _final(out)
        else:
            # Unknown/disabled agent: keep response read-only, no Notion ops mentions.
            out = AgentOutput(
                text=(
                    "Ne mogu pronaći traženog agenta za delegaciju. "
                    "Napiši tačan agent_id (npr. 'revenue_growth_operator' ili 'notion_ops') "
                    "ili koristi naziv iz liste aktivnih agenata."
                ),
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace={
                    "intent": "delegate_agent_task",
                    "exit_reason": "delegate_agent_task.unknown_target",
                    "requested_target": target_txt,
                    "snapshot": snap_trace,
                },
            )
            return _final(out)

    # Missing target: ask which agent, but keep it optional.
    if _looks_like_delegate_without_target(base_text):
        out = AgentOutput(
            text=_render_agent_picker(english=bool(english_output)),
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={
                "intent": "delegate_agent_task",
                "exit_reason": "delegate_agent_task.missing_target",
                "snapshot": snap_trace,
            },
        )
        return _final(out)

    # ---------------------------------------------
    # REAL delegation (deliverables) — confirmation-gated
    # ---------------------------------------------
    # SSOT rule:
    # - deliverable drafting must never be hijacked by weekly/kickoff (tasks empty is context only)
    # - deliverable confirm must NOT execute; it must replay the same proposal
    # - deliverable branch must never emit Notion proposals/toggles

    is_confirm = _is_deliverable_confirm(base_text)
    is_decline = _is_deliverable_decline(base_text)
    conv_state = ctx.get("conversation_state") if isinstance(ctx, dict) else None
    pending_deliverable = (
        _extract_last_deliverable_from_conversation_state(conv_state)
        if (is_confirm or continue_deliverable or is_decline)
        else None
    )

    # If the user is explicitly declining but also asking for advisory feedback,
    # do not short-circuit into deliverable-decline copy — cancel the pending
    # deliverable intent and continue normal READ-only advisory routing.
    if (
        is_decline
        and pending_deliverable
        and (
            _is_advisory_review_of_provided_content(base_text)
            or _is_advisory_thinking_request(base_text)
        )
    ):
        cid0 = _conversation_id()
        if isinstance(cid0, str) and cid0.strip():
            _deliverable_confirm_prompt_reset(conversation_id=cid0.strip())
        is_decline = False
        pending_deliverable = None

    def _build_rgo_delegation_proposal(
        *, task_text: str, reason: str
    ) -> ProposedCommand:
        return ProposedCommand(
            command="delegate_agent_task",
            args={
                "agent_id": "revenue_growth_operator",
                "task_text": (task_text or "").strip(),
                "endpoint": "/agents/execute",
                "canon": "deliverable_delegation.v1",
            },
            reason=reason,
            requires_approval=True,
            risk="LOW",
            scope="agents/execute",
            dry_run=True,
            payload_summary={
                "kind": "delegation",
                "command": "delegate_agent_task",
                "payload": {
                    "agent_id": "revenue_growth_operator",
                    "task_text": (task_text or "").strip(),
                },
                "endpoint": "/agents/execute",
                "canon": "CEO_CONSOLE_EXECUTION_FLOW",
                "source": "api_chat",
                "confidence_score": 0.7,
                "assumption_count": 0,
                "recommendation_type": "OPERATIONAL",
            },
        )

    # Explicit continuation keywords should resume the last deliverable even if
    # the new user message does not contain deliverable keywords.
    if continue_deliverable and pending_deliverable:
        task_text = (
            (pending_deliverable or "").strip()
            + "\n\nKorisnik traži iteraciju/nastavak: "
            + (base_text or "").strip()
        ).strip()

        proposed = _build_rgo_delegation_proposal(
            task_text=task_text,
            reason="Delegacija RGO za iteraciju deliverable-a (traži odobrenje).",
        )

        out = AgentOutput(
            text=(
                "Uredu — pripremio sam prijedlog delegacije za iteraciju. Odobri izvršenje."
                if not english_output
                else "OK — I prepared a delegation proposal for the iteration. Please approve execution."
            ),
            proposed_commands=[proposed],
            agent_id="ceo_advisor",
            read_only=True,
            trace={
                "intent": "deliverable_continue_proposal",
                "delegation_target": "revenue_growth_operator",
                "delegation_reason": "deliverable_continue_proposal",
                "fallback_used": "none",
                "snapshot": snap_trace,
            },
        )
        return _final(out)

    # After a successful deliverable execution, do NOT keep re-executing the same
    # deliverable on subsequent generic confirmations. Re-evaluate the message as
    # a NEW intent (unless user explicitly asked to continue/iterate).
    if is_confirm and pending_deliverable:
        cid = _conversation_id()
        if (
            isinstance(cid, str)
            and cid.strip()
            and _was_deliverable_completed(
                conversation_id=cid.strip(), task_text=pending_deliverable
            )
        ):
            # Treat this as a normal message (ignore the old pending deliverable).
            is_confirm = False
            pending_deliverable = None

    if is_confirm and pending_deliverable:
        cid0 = _conversation_id()
        if isinstance(cid0, str) and cid0.strip():
            _deliverable_confirm_prompt_reset(conversation_id=cid0.strip())

        proposed = _build_rgo_delegation_proposal(
            task_text=pending_deliverable,
            reason="Delegacija RGO za izradu deliverable-a (traži odobrenje).",
        )

        out = AgentOutput(
            text=(
                "Uredu — potvrđeno. Evo istog prijedloga delegacije ponovo za odobrenje."
                if not english_output
                else "OK — confirmed. Replaying the same delegation proposal for approval."
            ),
            proposed_commands=[proposed],
            agent_id="ceo_advisor",
            read_only=True,
            trace={
                "intent": "deliverable_confirm_replay",
                "delegation_target": "revenue_growth_operator",
                "delegation_reason": "deliverable_confirm_replay",
                "fallback_used": "none",
                "snapshot": snap_trace,
            },
        )
        return _final(out)

    # User explicitly declined delegation: don't keep asking.
    if is_decline and pending_deliverable:
        cid0 = _conversation_id()
        if isinstance(cid0, str) and cid0.strip():
            _deliverable_confirm_prompt_reset(conversation_id=cid0.strip())

        out = AgentOutput(
            text=(
                "Uredu — ne delegiram deliverable-e. Reci tačno šta želiš umjesto toga (npr. plan/prioriteti/strategija), pa ću pomoći ovdje."
                if not english_output
                else "OK — I won't delegate deliverables. Tell me what you want instead (e.g., a plan/priorities/strategy), and I'll help here."
            ),
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={
                "intent": "deliverable_declined",
                "exit_reason": "deliverable.declined",
                "snapshot": snap_trace,
            },
        )
        return _final(out)

    if intent == "deliverable" and not is_confirm:
        # ACK discipline: if the user is actually asking for a plan (not deliverables),
        # ask a clarifying question instead of proposing delegation.
        if _has_plan_keywords(base_text) and (not _has_deliverable_markers(base_text)):
            return _final(
                AgentOutput(
                    text=(
                        "Da potvrdim: želiš plan/prioritete (bez konkretnih poruka/emailova), ili želiš i deliverable-e?"
                        if not english_output
                        else "Quick check: do you want a plan/priorities (no concrete messages/emails), or do you want deliverables too?"
                    ),
                    proposed_commands=[],
                    agent_id="ceo_advisor",
                    read_only=True,
                    trace={
                        "intent": "deliverable_clarify_plan_vs_deliverables",
                        "exit_reason": "deliverable.ack_clarify",
                        "snapshot": snap_trace,
                    },
                )
            )

        ack = _delegation_ack_text(user_text=base_text, english=bool(english_output))
        if not ack:
            return _final(
                AgentOutput(
                    text=(
                        "Da bih predložio delegaciju, trebam 1 detalj: šta je cilj deliverable-a i koji je rok?"
                        if not english_output
                        else "Before I propose delegation, one detail: what's the deliverable objective and deadline?"
                    ),
                    proposed_commands=[],
                    agent_id="ceo_advisor",
                    read_only=True,
                    trace={
                        "intent": "deliverable_clarify_missing_ack_fields",
                        "exit_reason": "deliverable.ack_missing",
                        "snapshot": snap_trace,
                    },
                )
            )

        # Loop safeguard: if we've already asked for confirmation a few times and
        # the user keeps responding with non-confirm/non-continue, stop prompting.
        cid0 = _conversation_id()
        if isinstance(cid0, str) and cid0.strip():
            cnt = _deliverable_confirm_prompt_count(conversation_id=cid0.strip())
            if cnt >= 2:
                _deliverable_confirm_prompt_reset(conversation_id=cid0.strip())
                out = AgentOutput(
                    text=(
                        "Neću više tražiti potvrdu za delegaciju. Ako želiš samo plan (bez deliverable-a), reci vremenski okvir i cilj, pa ću sastaviti plan."
                        if not english_output
                        else "I won't keep asking for delegation confirmation. If you want a plan (without deliverables), tell me the timeframe and objective and I'll draft the plan."
                    ),
                    proposed_commands=[],
                    agent_id="ceo_advisor",
                    read_only=True,
                    trace={
                        "intent": "deliverable_confirmation_loop_break",
                        "exit_reason": "deliverable.confirmation_loop_break",
                        "snapshot": snap_trace,
                    },
                )
                return _final(out)

        # Proposal-only: emit an approval-gated delegation proposal (no execution).
        proposed = _build_rgo_delegation_proposal(
            task_text=base_text,
            reason="Delegacija Revenue & Growth Operatoru za izradu deliverable-a (traži odobrenje).",
        )
        txt = (
            "Mogu delegirati Revenue & Growth Operatoru da napiše konkretne deliverable-e (email/poruke/sekvence).\n"
            "Želiš da delegiram? Potvrdi: 'da' / 'želim' / 'uradi to' / 'slažem se'."
            if not english_output
            else "I can delegate to Revenue & Growth Operator to draft the concrete deliverables (emails/messages/sequences).\n"
            "To proceed, confirm: 'yes' / 'go ahead' / 'proceed'."
        )
        if ack:
            txt = (ack.strip() + "\n\n" + txt).strip()

        out = AgentOutput(
            text=txt,
            proposed_commands=[proposed],
            agent_id="ceo_advisor",
            read_only=True,
            trace={
                "intent": "deliverable_proposal",
                "delegation_target": "revenue_growth_operator",
                "fallback_used": "none",
                "snapshot": snap_trace,
            },
        )

        if isinstance(cid0, str) and cid0.strip():
            _deliverable_confirm_prompt_bump(conversation_id=cid0.strip())

        if _debug_trace_enabled():
            out.trace["debug_trace"] = {
                "selected_agent_id": "ceo_advisor",
                "delegation_target": "revenue_growth_operator",
                "delegation_reason": "deliverable_intent_requires_confirmation",
                "fallback_used": "none",
                "inputs_used": {
                    "tasks_empty": bool(not bool(tasks)),
                    "notion_snapshot_present": bool(
                        isinstance(snapshot_payload, dict) and bool(snapshot_payload)
                    ),
                },
            }

        return _final(out)

    # Deterministic fallback when tasks are empty for planning/help prompts.
    # Keep this BEFORE Responses-mode grounding guard; it must not call LLM/executor.
    projects = None
    try:
        projects = (
            snapshot_payload.get("projects")
            if isinstance(snapshot_payload, dict)
            else None
        )
    except Exception:
        projects = None

    wants_weekly_plan = intent == "weekly"

    # Only trigger when snapshot explicitly contains a tasks list.
    if (
        (not tasks)
        and wants_weekly_plan
        and isinstance(snapshot_payload, dict)
        and ("tasks" in snapshot_payload)
    ):
        return _final(
            _empty_tasks_fallback_output(
                base_text=base_text,
                goals=goals,
                projects=projects,
                memory_snapshot=ctx.get("memory") if isinstance(ctx, dict) else None,
                conversation_state=ctx.get("conversation_state")
                if isinstance(ctx, dict)
                else None,
                english_output=english_output,
                snap_trace=snap_trace,
            )
        )

    structured_mode = _needs_structured_snapshot_answer(base_text)
    propose_only = _is_propose_only_request(base_text)
    wants_notion = _wants_notion_task_or_goal(base_text)
    wants_prompt_template = _is_prompt_preparation_request(base_text)

    use_llm = not propose_only

    # Grounding gate: for fact-sensitive questions, never assert state without snapshot.
    # This prevents hallucinated "blocked/at risk" type claims.
    snapshot_has_facts = _snapshot_has_business_facts(snapshot_payload)
    fact_sensitive = _is_fact_sensitive_query(base_text)

    # Grounding pack (if present): used to decide whether we have curated KB coverage.
    gp_ctx = ctx.get("grounding_pack") if isinstance(ctx, dict) else None
    gp_ctx = gp_ctx if isinstance(gp_ctx, dict) else {}
    kb_used_ids: List[str] = []
    kb_entries_effective: List[Dict[str, Any]] = []
    kb_hits: int = 0
    kb_mode: str = "none"  # stable diagnostic: where KB was read from
    try:
        kb_retrieved = gp_ctx.get("kb_retrieved") if isinstance(gp_ctx, dict) else None
        if isinstance(kb_retrieved, dict):
            kb_mode = "grounding_pack.kb_retrieved"
        else:
            # Back-compat: some bridges provide KB retrieval as ctx["kb"].
            kb_retrieved = ctx.get("kb") if isinstance(ctx, dict) else None
            if isinstance(kb_retrieved, dict):
                kb_mode = "ctx.kb"

        if isinstance(kb_retrieved, dict):
            kb_used_ids = list(kb_retrieved.get("used_entry_ids") or [])
            entries0 = kb_retrieved.get("entries")
            if isinstance(entries0, list):
                kb_entries_effective = [x for x in entries0 if isinstance(x, dict)]
                kb_hits = len(kb_entries_effective)
    except Exception:
        kb_used_ids = []
        kb_entries_effective = []
        kb_hits = 0
        kb_mode = "none"
    kb_used_ids = [x for x in kb_used_ids if isinstance(x, str) and x.strip()]
    kb_ids_used_count = len(kb_used_ids)

    # Deterministic: list available agents from the runtime registry.
    # This should never call LLM and should not be satisfied by KB snippets.
    if (not fact_sensitive) and _is_agent_registry_question(base_text):
        txt = _render_agent_registry_text(english_output=english_output)
        return _final(
            AgentOutput(
                text=txt,
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace={
                    "deterministic": True,
                    "intent": "agent_registry",
                    "exit_reason": "deterministic.agent_registry",
                    "kb_used_entry_ids": kb_used_ids,
                    "snapshot": snap_trace,
                },
            )
        )

    # TRACE_STATUS / provenance query: answer from grounding trace, never from memory governance.
    t_prompt0 = (base_text or "").strip().lower()
    if _is_trace_status_query(t_prompt0):
        tr2 = None
        try:
            tr2 = gp_ctx.get("trace") if isinstance(gp_ctx, dict) else None
        except Exception:
            tr2 = None

        tr2 = tr2 if isinstance(tr2, dict) else {}

        used0 = tr2.get("used_sources") if isinstance(tr2, dict) else None
        used_list0 = [
            str(x).strip()
            for x in (used0 or [])
            if isinstance(x, str) and str(x).strip()
        ]

        has_snapshot_ctx = bool(
            isinstance(snap_trace, dict)
            and (
                snap_trace.get("present_in_request")
                or snap_trace.get("available")
                or int(snap_trace.get("goals_count") or 0) > 0
                or int(snap_trace.get("tasks_count") or 0) > 0
            )
        )
        has_any_source = bool(used_list0 or kb_used_ids or has_snapshot_ctx)

        if not has_any_source:
            txt = _trace_no_sources_text(english_output=english_output)
        else:
            txt = _build_trace_status_text(trace_v2=tr2, english_output=english_output)
            extra: List[str] = []
            if kb_used_ids:
                extra.append("KB: " + ", ".join(kb_used_ids))
            if isinstance(snap_trace, dict) and has_snapshot_ctx:
                extra.append(
                    "Snapshot: present=%s ready=%s goals=%s tasks=%s"
                    % (
                        bool(snap_trace.get("present_in_request")),
                        bool(snap_trace.get("ready")),
                        int(snap_trace.get("goals_count") or 0),
                        int(snap_trace.get("tasks_count") or 0),
                    )
                )
            if extra:
                txt = (txt.strip() + "\n" + "\n".join(extra)).strip()
        return _final(
            AgentOutput(
                text=txt,
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace={
                    "deterministic": True,
                    "intent": "trace_status",
                    "kb_used_entry_ids": kb_used_ids,
                    "snapshot": snap_trace,
                },
            )
        )

    # Deterministic capability Q&A for memory (never needs LLM).
    t0 = (base_text or "").strip().lower()
    if (not fact_sensitive) and _is_memory_capability_question(t0):
        return _final(
            AgentOutput(
                text=_memory_capability_text(english_output=english_output),
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace={
                    "deterministic": True,
                    "intent": "memory_capability",
                    "kb_used_entry_ids": kb_used_ids,
                    "snapshot": snap_trace,
                },
            )
        )

    # Deterministic: explicit user choice to persist/expand knowledge should
    # always result in an approval-gated proposal (never silent writes).
    if (not fact_sensitive) and (
        _is_memory_write_request(t0) or _is_expand_knowledge_request(t0)
    ):
        detail = _extract_after_colon(base_text)
        if not detail:
            detail = base_text

        # Canonical, deterministic memory_write.v1 payload (no free-form prompt).
        item_text = _normalize_item_text(detail)
        item_type = _deterministic_memory_item_type(base_text)
        tags = ["memory_write", "user_note"]
        source = "user"
        idem = _memory_idempotency_key(
            item_type=item_type,
            item_text=item_text,
            tags=tags,
            source=source,
        )
        grounded_on = ["KB:memory_model_001", "identity_pack.kernel.system_safety"]

        gp_ctx0 = ctx.get("grounding_pack") if isinstance(ctx, dict) else None
        gp_ctx0 = gp_ctx0 if isinstance(gp_ctx0, dict) else {}
        identity_hash = None
        try:
            ip = gp_ctx0.get("identity_pack") if isinstance(gp_ctx0, dict) else None
            if isinstance(ip, dict):
                identity_hash = ip.get("hash")
        except Exception:
            identity_hash = None

        memory_write_payload: Dict[str, Any] = {
            "schema_version": "memory_write.v1",
            "approval_required": True,
            "idempotency_key": idem,
            "grounded_on": grounded_on,
            "item": {
                "type": item_type,
                "text": item_text,
                "tags": tags,
                "source": source,
            },
        }

        txt = (
            (
                "Razumijem. Mogu pripremiti prijedlog da ovo upišemo u memoriju/znanje, ali to zahtijeva odobrenje.\n\n"
                "Ako želiš upis u Notion (DB/page), prvo aktiviraj Notion Ops: 'notion ops aktiviraj'."
            )
            if not english_output
            else (
                "Got it. I can prepare a proposal to store this in memory/knowledge, but it requires approval.\n\n"
                "If you want a Notion write (DB/page), arm Notion Ops first: 'notion ops activate'."
            )
        )

        return _final(
            AgentOutput(
                text=txt,
                proposed_commands=[
                    ProposedCommand(
                        command=PROPOSAL_WRAPPER_INTENT,
                        intent="memory_write",
                        args=memory_write_payload,
                        reason="Approval-gated memory/knowledge write proposal.",
                        requires_approval=True,
                        risk="LOW",
                        dry_run=True,
                        scope="api_execute_raw",
                        payload_summary={
                            "schema_version": "memory_write.v1",
                            "identity_id": identity_hash,
                            "grounded_on": grounded_on,
                            "idempotency_key": idem,
                        },
                    )
                ],
                agent_id="ceo_advisor",
                read_only=True,
                trace={
                    "deterministic": True,
                    "intent": "memory_or_expand_knowledge",
                    "kb_used_entry_ids": kb_used_ids,
                    "proposal_kind": "memory_write",
                    "schema_version": "memory_write.v1",
                    "idempotency_key": idem,
                    "grounded_on_count": len(grounded_on),
                    "snapshot": snap_trace,
                },
            )
        )

    # Enterprise unknown-mode: if the grounding layer retrieved no curated KB
    # entries for this prompt, do not answer from general model knowledge.
    # Keep the chat going with clarifying questions and an explicit expand-knowledge option.
    if (
        (not fact_sensitive)
        and (kb_hits == 0)
        and (not snapshot_has_facts)
        and (not _should_use_kickoff_in_offline_mode(t0))
        and (not advisory_review)
        and (not (wants_prompt_template and wants_notion))
    ):
        effective_allow_general = bool(allow_general and llm_configured)
        logger.info(
            "[LLM-GATE] unknown_mode: allow_general=%s llm_configured=%s effective_allow_general=%s kb_ids_used_count=%s kb_hits=%s kb_mode=%s",
            allow_general,
            llm_configured,
            effective_allow_general,
            kb_ids_used_count,
            kb_hits,
            kb_mode,
        )
        if not effective_allow_general:
            if not allow_general:
                logger.warning(
                    "[LLM-GATE] Blocked: allow_general is False, returning KB-only fallback."
                )
            else:
                # Strict mode takes precedence: if the caller explicitly requires
                # LLM execution, surface a typed configuration error instead of
                # silently falling back.
                if _strict_llm_required(meta):
                    logger.error(
                        "[LLM-GATE] Blocked (strict): allow_general is True but LLM is not configured; raising LLMNotConfiguredError."
                    )
                    logger.error("[CEO_ADVISOR_EXIT] error.llm_not_configured")
                    raise LLMNotConfiguredError(
                        "error.llm_not_configured: CEO Advisor LLM path blocked: allow_general is True but _llm_is_configured() is False. "
                        "Check OPENAI_API_KEY and LLM configuration."
                    )
                logger.warning(
                    "[LLM-GATE] Blocked: allow_general is True but LLM is not configured; returning offline-safe unknown_mode fallback."
                )
            fallback_reason = (
                "fallback.allow_general_false"
                if not allow_general
                else "offline.llm_not_configured"
            )
            return _final(
                AgentOutput(
                    text=(
                        "Trenutno nemam to znanje (nije u kuriranom KB-u / trenutnom snapshotu).\n\n"
                        "Opcije:\n"
                        "1) Razjasni: odgovori na 1–3 pitanja i daću najbolji mogući odgovor (jasno ću označiti pretpostavke).\n"
                        "2) Proširi znanje: napiši 'Proširi znanje: ...' i pripremiću approval-gated prijedlog za upis.\n\n"
                        "Brza pitanja:\n"
                        "- Šta ti tačno treba: definicija, odluka ili plan implementacije?\n"
                        "- Koji je kontekst/domena (biz/tech/legal)?\n"
                        "- Koja su ograničenja (vrijeme, alati, scope)?"
                    ),
                    proposed_commands=[],
                    agent_id="ceo_advisor",
                    read_only=True,
                    notion_ops={
                        "armed": False,
                        "armed_at": None,
                        "session_id": None,
                        "armed_state": {"armed": False, "armed_at": None},
                    },
                    trace={
                        "deterministic": True,
                        "intent": "unknown_mode",
                        "kb_used_entry_ids": kb_used_ids,
                        "snapshot": snap_trace,
                        "exit_reason": fallback_reason,
                        "llm_gate_diag": {
                            "kb_ids_used_count": int(kb_ids_used_count),
                            "kb_hits": int(kb_hits),
                            "kb_mode": kb_mode,
                            "fallback_reason": fallback_reason,
                        },
                    },
                )
            )
        # else: allow_general==True, nastavi do LLM path-a
    if fact_sensitive and not snapshot_has_facts:
        trace = ctx.get("trace") if isinstance(ctx, dict) else {}
        if not isinstance(trace, dict):
            trace = {}

        # Advisory/thinking prompts should not be hard-blocked by SSOT/snapshot.
        # Provide safe coaching without asserting business facts.
        if (
            advisory_review
            or _is_planning_or_help_request(base_text)
            or _is_advisory_thinking_request(base_text)
        ):
            trace["grounding_gate"] = {
                "applied": True,
                "reason": "fact_sensitive_no_snapshot_but_advisory_intent",
                "snapshot": snap_trace,
                "bypassed": True,
            }
            trace["exit_reason"] = "ok"
            logger.info("[CEO_ADVISOR_EXIT] ok.advisory_no_snapshot")
            return _final(
                AgentOutput(
                    text=_advisory_no_snapshot_safe_analysis_text(
                        english_output=english_output
                    ),
                    proposed_commands=[],
                    agent_id="ceo_advisor",
                    read_only=True,
                    trace=trace,
                )
            )

        trace["grounding_gate"] = {
            "applied": True,
            "reason": "fact_sensitive_query_without_snapshot",
            "snapshot": snap_trace,
        }
        trace["exit_reason"] = "fallback.fact_sensitive_no_snapshot"
        logger.info("[CEO_ADVISOR_EXIT] fallback.fact_sensitive_no_snapshot")
        return _final(
            AgentOutput(
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
            return _final(
                AgentOutput(
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
            )

        if (tgt in {"goals", "both"} and goals) or (tgt in {"tasks", "both"} and tasks):
            if tgt == "goals":
                text_out = _render_snapshot_summary(goals, [])
            elif tgt == "tasks":
                text_out = _render_snapshot_summary([], tasks)
            else:
                text_out = _render_snapshot_summary(goals, tasks)

            return _final(
                AgentOutput(
                    text=text_out,
                    proposed_commands=[],
                    agent_id="ceo_advisor",
                    read_only=True,
                    trace={"snapshot": snap_trace},
                )
            )

        # No data: give a precise read-path message instead of generic coaching.
        return _final(
            AgentOutput(
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
        )

    # Continue processing normally...
    # If snapshot is empty and LLM isn't configured, return a deterministic
    # kickoff response (tests/CI and offline deployments).
    if (
        structured_mode
        and not goals
        and not tasks
        and (not snapshot_ready)
        and (not _is_advisory_review_of_provided_content(base_text))
        and (_is_empty_state_kickoff_prompt(base_text) or not _llm_is_configured())
    ):
        kickoff = _default_kickoff_text()
        return _final(
            AgentOutput(
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
        )

    # -------------------------------
    # Deterministic offline behavior (enterprise)
    # -------------------------------
    # If OpenAI/LLM isn't configured (or is intentionally disabled in CI/offline
    # deployments), we must NOT default to the GOALS/TASKS dashboard for unrelated
    # knowledge/system questions. Instead, use unknown-mode and/or approval-gated
    # proposals for explicit "remember/expand knowledge" requests.
    if use_llm and allow_general and not llm_configured:
        logger.error(
            "[LLM-GATE] Blocked: allow_general is True but _llm_is_configured is False (missing OPENAI_API_KEY or misconfiguration)."
        )
        logger.error("[CEO_ADVISOR_EXIT] offline.llm_not_configured")
        if _strict_llm_required(meta):
            raise LLMNotConfiguredError(
                "error.llm_not_configured: CEO Advisor LLM path blocked: allow_general is True but _llm_is_configured() is False. "
                "Check OPENAI_API_KEY and LLM configuration."
            )

    if use_llm and not llm_configured:
        logger.warning(
            "[LLM-GATE] Blocked: use_llm is True but _llm_is_configured is False. Returning deterministic fallback."
        )
        # If KB retrieval returned hits/ids, do NOT claim "no curated knowledge".
        # Return a deterministic grounded response using the retrieved KB snippets.
        if kb_ids_used_count > 0 or kb_hits > 0:
            kb_lines: List[str] = []
            for it in kb_entries_effective[:8]:
                kid = (it.get("id") if isinstance(it, dict) else None) or "(missing_id)"
                title = (it.get("title") if isinstance(it, dict) else None) or ""
                content = (it.get("content") if isinstance(it, dict) else None) or ""
                snippet = _truncate(str(content), max_chars=500)
                if title:
                    kb_lines.append(f"- [KB:{kid}] {title}: {snippet}")
                else:
                    kb_lines.append(f"- [KB:{kid}] {snippet}")

            if english_output:
                text_out = (
                    "I found relevant curated KB entries for this request, but the LLM is not configured in this environment.\n"
                    "Here are the retrieved KB snippets:\n\n"
                    + (
                        "\n".join(kb_lines)
                        if kb_lines
                        else "(KB hits present, but entries payload was empty)"
                    )
                )
            else:
                text_out = (
                    "Imam relevantne unose iz kuriranog KB-a za ovaj upit, ali LLM nije konfigurisan u ovom okruženju.\n"
                    "Evo izvučenih KB snippeta:\n\n"
                    + (
                        "\n".join(kb_lines)
                        if kb_lines
                        else "(KB hitovi postoje, ali payload entries je prazan)"
                    )
                )

            fallback_reason = "offline.kb_grounded_no_llm"
            return _final(
                AgentOutput(
                    text=text_out,
                    proposed_commands=[],
                    agent_id="ceo_advisor",
                    read_only=True,
                    trace={
                        "offline_mode": True,
                        "deterministic": True,
                        "intent": "offline_kb_grounded",
                        "exit_reason": fallback_reason,
                        "kb_used_entry_ids": kb_used_ids,
                        "snapshot": snap_trace,
                        "llm_gate_diag": {
                            "kb_ids_used_count": int(kb_ids_used_count),
                            "kb_hits": int(kb_hits),
                            "kb_mode": kb_mode,
                            "fallback_reason": fallback_reason,
                        },
                    },
                )
            )

        t0 = (base_text or "").strip().lower()

        # Advisory review of user-provided content must not fall into unknown-mode.
        if _is_advisory_review_of_provided_content(base_text):
            return AgentOutput(
                text=_advisory_review_fallback_text(english_output=english_output),
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace={
                    "offline_mode": True,
                    "deterministic": True,
                    "intent": "advisory_review",
                    "exit_reason": "offline.llm_not_configured_advisory_review",
                    "snapshot": snap_trace,
                },
            )

        # Prompt-template intent should return a copy/paste template even offline.
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
            trace["offline_mode"] = True
            return AgentOutput(
                text=text_out,
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace=trace,
            )

        if _is_memory_capability_question(t0):
            return AgentOutput(
                text=_memory_capability_text(english_output=english_output),
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace={
                    "offline_mode": True,
                    "deterministic": True,
                    "intent": "memory_capability",
                    "snapshot": snap_trace,
                },
            )

        if _is_memory_write_request(t0) or _is_expand_knowledge_request(t0):
            detail = _extract_after_colon(base_text)
            if not detail:
                detail = base_text

            wrapper_prompt = (
                "Prepare a write proposal (requires approval) to persist the following into canonical memory/knowledge. "
                "Use intent=memory_write. Params should include a single field 'note' with the raw user text. "
                f"USER_NOTE: {detail}"
            )

            txt = (
                (
                    "Razumijem. Mogu pripremiti prijedlog da ovo upišemo u memoriju/znanje, ali to zahtijeva odobrenje.\n\n"
                    "Ako želiš upis u Notion (DB/page), prvo aktiviraj Notion Ops: 'notion ops aktiviraj'."
                )
                if not english_output
                else (
                    "Got it. I can prepare a proposal to store this in memory/knowledge, but it requires approval.\n\n"
                    "If you want a Notion write (DB/page), arm Notion Ops first: 'notion ops activate'."
                )
            )

            return AgentOutput(
                text=txt,
                proposed_commands=[
                    ProposedCommand(
                        command=PROPOSAL_WRAPPER_INTENT,
                        args={"prompt": wrapper_prompt},
                        reason="Approval-gated memory/knowledge write proposal.",
                        requires_approval=True,
                        risk="LOW",
                        dry_run=True,
                        scope="api_execute_raw",
                    )
                ],
                agent_id="ceo_advisor",
                read_only=True,
                trace={
                    "offline_mode": True,
                    "deterministic": True,
                    "intent": "memory_or_expand_knowledge",
                    "snapshot": snap_trace,
                },
            )

        # In offline mode (no LLM configured), always return a deterministic response.
        # Tests/CI enforce this to avoid external network IO.
        if not snapshot_has_facts and _should_use_kickoff_in_offline_mode(t0):
            return AgentOutput(
                text=_default_kickoff_text(),
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
                    "offline_mode": True,
                    "deterministic": True,
                    "intent": "kickoff",
                    "exit_reason": "offline.llm_not_configured",
                    "snapshot": snap_trace,
                },
            )

        fallback_reason = "offline.llm_not_configured"
        return _final(
            AgentOutput(
                text=_unknown_mode_text(english_output=english_output),
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace={
                    "offline_mode": True,
                    "deterministic": True,
                    "intent": "unknown_mode",
                    "exit_reason": fallback_reason,
                    "snapshot": snap_trace,
                    "llm_gate_diag": {
                        "kb_ids_used_count": int(kb_ids_used_count),
                        "kb_hits": int(kb_hits),
                        "kb_mode": kb_mode,
                        "fallback_reason": fallback_reason,
                    },
                },
            )
        )

    # Nastavi sa ostatkom koda...
    safe_context: Dict[str, Any] = {
        "canon": {"read_only": True, "no_tools": True, "no_side_effects": True},
        "snapshot": snapshot_payload,
        "identity_pack": getattr(agent_input, "identity_pack", {})
        if isinstance(getattr(agent_input, "identity_pack", None), dict)
        else {},
        "memory": ctx.get("memory") if isinstance(ctx, dict) else None,
        "conversation_state": ctx.get("conversation_state")
        if isinstance(ctx, dict)
        else None,
        "metadata": {
            **(agent_input.metadata if isinstance(agent_input.metadata, dict) else {}),
            "structured_mode": bool(structured_mode),
        },
    }

    gp = ctx.get("grounding_pack") if isinstance(ctx, dict) else None
    if isinstance(gp, dict) and gp:
        safe_context["grounding_pack"] = gp
    else:
        # Back-compat: when KB retrieval is bridged as ctx["kb"], inject it into
        # synthesis context so LLM sees the snippets (not trace-only).
        kb_ctx = ctx.get("kb") if isinstance(ctx, dict) else None
        if isinstance(kb_ctx, dict) and (kb_ids_used_count > 0 or kb_hits > 0):
            safe_context["grounding_pack"] = {
                "enabled": True,
                "kb_retrieved": kb_ctx,
            }

    # RESPONSES MODE: enforce system-equivalent instructions (identity + governance + budgeted grounding).
    if _responses_mode_enabled():
        if not _grounding_sufficient_for_responses_llm(gp):
            # Enterprise exception: advisory review/thinking over user-provided content must not be blocked
            # by missing grounding_pack. Keep it read-only and avoid any SSOT claims.
            if (
                _is_advisory_review_of_provided_content(base_text)
                or _is_advisory_thinking_request(base_text)
                or _is_planning_or_help_request(base_text)
            ):
                trace = ctx.get("trace") if isinstance(ctx, dict) else {}
                if not isinstance(trace, dict):
                    trace = {}
                trace["grounding_gate"] = {
                    "applied": True,
                    "reason": "responses_mode_missing_grounding_but_advisory_intent",
                    "snapshot": snap_trace,
                    "bypassed": True,
                }
                trace["exit_reason"] = "ok"
                logger.info("[CEO_ADVISOR_EXIT] ok.advisory_no_snapshot")
                return _final(
                    AgentOutput(
                        text=_advisory_no_snapshot_safe_analysis_text(
                            english_output=english_output
                        ),
                        proposed_commands=[],
                        agent_id="ceo_advisor",
                        read_only=True,
                        trace=trace,
                    )
                )

            logger.warning(
                "[CEO_ADVISOR_RESPONSES_GUARD] blocked: missing/insufficient grounding_pack"
            )
            return _final(
                AgentOutput(
                    text=_responses_missing_grounding_text(
                        english_output=english_output
                    ),
                    proposed_commands=[],
                    agent_id="ceo_advisor",
                    read_only=True,
                    trace={
                        "deterministic": True,
                        "intent": "missing_grounding",
                        "exit_reason": "blocked.missing_grounding",
                        "snapshot": snap_trace,
                    },
                )
            )

        conv_state = ctx.get("conversation_state") if isinstance(ctx, dict) else None
        instructions = build_ceo_instructions(
            gp,
            conversation_state=conv_state,
            notion_ops={
                "armed": bool(notion_ops_armed is True),
                "armed_at": notion_ops_state.get("armed_at")
                if isinstance(notion_ops_state, dict)
                else None,
                "session_id": session_id,
            },
        )
        safe_context["instructions"] = instructions

        # Local hard-guard (no guessing): never call LLM without non-empty instructions.
        if not isinstance(instructions, str) or not instructions.strip():
            logger.error("[CEO_ADVISOR_RESPONSES_GUARD] blocked: instructions empty")
            return _final(
                AgentOutput(
                    text=_responses_missing_grounding_text(
                        english_output=english_output
                    ),
                    proposed_commands=[],
                    agent_id="ceo_advisor",
                    read_only=True,
                    trace={
                        "deterministic": True,
                        "intent": "missing_instructions",
                        "exit_reason": "blocked.missing_instructions",
                        "snapshot": snap_trace,
                    },
                )
            )

        # DEBUG (no sensitive content): section lengths + hashes
        try:
            identity_i = instructions.find("\n\nIDENTITY:\n")
            kb_i = instructions.find("\n\nKB_CONTEXT:\n")
            notion_i = instructions.find("\n\nNOTION_SNAPSHOT:\n")
            mem_i = instructions.find("\n\nMEMORY_CONTEXT:\n")
            # Best-effort extraction
            sec_identity = (
                instructions[identity_i:kb_i] if identity_i != -1 and kb_i != -1 else ""
            )
            sec_kb = (
                instructions[kb_i:notion_i] if kb_i != -1 and notion_i != -1 else ""
            )
            sec_notion = (
                instructions[notion_i:mem_i] if notion_i != -1 and mem_i != -1 else ""
            )
            sec_mem = instructions[mem_i:] if mem_i != -1 else ""
            kb_entries = 0
            try:
                kb_retrieved = gp.get("kb_retrieved") if isinstance(gp, dict) else None
                if isinstance(kb_retrieved, dict):
                    kb_entries = len(kb_retrieved.get("entries") or [])
            except Exception:
                kb_entries = 0
            logger.info(
                "[CEO_ADVISOR_RESPONSES_INSTRUCTIONS] total_len=%s total_hash=%s kb_entries=%s identity_len=%s identity_hash=%s kb_len=%s kb_hash=%s notion_len=%s notion_hash=%s memory_len=%s memory_hash=%s",
                len(instructions),
                _sha256_prefix(instructions),
                kb_entries,
                len(sec_identity),
                _sha256_prefix(sec_identity),
                len(sec_kb),
                _sha256_prefix(sec_kb),
                len(sec_notion),
                _sha256_prefix(sec_notion),
                len(sec_mem),
                _sha256_prefix(sec_mem),
            )
        except Exception:
            logger.info(
                "[CEO_ADVISOR_RESPONSES_INSTRUCTIONS] total_len=%s total_hash=%s",
                len(instructions),
                _sha256_prefix(instructions),
            )

    if structured_mode:
        prompt_text = _format_enforcer(base_text, english_output)
    else:
        prompt_text = (
            f"{base_text}\n\n"
            "Return only valid json (a single JSON object). "
            'Required keys: "text" (string) and "proposed_commands" (array; can be empty). '
            "Do not wrap the json in markdown code fences.\n"
            "Ako predlaže akciju, vrati je u proposed_commands. "
            "Ne izvršavaj ništa."
        )

        # Grounding: require explicit KB citations when using curated knowledge.
        if isinstance(gp, dict) and gp:
            kb_ids = []
            try:
                kb_retrieved = gp.get("kb_retrieved")
                if isinstance(kb_retrieved, dict):
                    kb_ids = list(kb_retrieved.get("used_entry_ids") or [])
            except Exception:
                kb_ids = []

            kb_ids = [x for x in kb_ids if isinstance(x, str) and x.strip()]
            if kb_ids:
                prompt_text += (
                    "\n\nGROUNDING (KB citations required): "
                    "Ako koristiš kurirano znanje iz KB, moraš citirati tačne KB entry id-je "
                    "u formatu [KB:<id>]. "
                    f"Dozvoljeni KB ids: {', '.join(kb_ids)}."
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
    llm_exit_reason: Optional[str] = None
    llm_executor_error_diag: Optional[Dict[str, Any]] = None

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
        return _final(
            AgentOutput(
                text=text_out,
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace=trace,
            )
        )

    if use_llm:
        try:
            from services.agent_router.executor_factory import get_executor

            executor = get_executor(purpose="ceo_advisor")
            logger.info(f"[LLM-GATE] executor selection: {executor.__class__.__name__}")
            prompt_text += (
                "\n\nReturn only valid json (a single JSON object). "
                'Required keys: "text" (string) and "proposed_commands" (array; can be empty). '
                "Do not wrap the json in markdown code fences."
            )
            raw = await executor.ceo_command(text=prompt_text, context=safe_context)
            if isinstance(raw, dict):
                result = raw
            else:
                result = {"text": str(raw)}
            llm_exit_reason = "llm.success"
            logger.info("[CEO_ADVISOR_EXIT] llm.success")
        except Exception as exc:
            logger.exception("[LLM-GATE] Exception in LLM execution")
            llm_exit_reason = "offline.executor_error"
            logger.info("[CEO_ADVISOR_EXIT] offline.executor_error")

            # Detect OpenAI authentication failure (401 invalid_api_key) so it can't
            # be misdiagnosed as missing KB/snapshot knowledge.
            try:
                from openai import AuthenticationError  # type: ignore

                if isinstance(exc, AuthenticationError):
                    status = getattr(exc, "status_code", None)
                    resp = getattr(exc, "response", None)
                    if status is None and resp is not None:
                        status = getattr(resp, "status_code", None)

                    body = getattr(exc, "body", None)
                    code = None
                    if isinstance(body, dict):
                        err0 = body.get("error")
                        if isinstance(err0, dict):
                            code = err0.get("code")
                    if code is None and isinstance(body, dict):
                        code = body.get("code")

                    if int(status or 0) == 401 or str(code or "") == "invalid_api_key":
                        llm_executor_error_diag = {
                            "status": 401,
                            "code": "invalid_api_key",
                            "kind": "auth",
                        }
            except Exception:
                llm_executor_error_diag = llm_executor_error_diag

            # Enterprise fail-soft: do not dump LLM errors; return deterministic unknown-mode.
            t0 = (base_text or "").strip().lower()
            if _is_memory_capability_question(t0):
                result = {
                    "text": _memory_capability_text(english_output=english_output),
                    "proposed_commands": [],
                }
            elif (
                _is_advisory_review_of_provided_content(base_text)
                or _is_advisory_thinking_request(base_text)
                or _is_planning_or_help_request(base_text)
            ):
                result = {
                    "text": _advisory_no_snapshot_safe_analysis_text(
                        english_output=english_output
                    ),
                    "proposed_commands": [],
                }
            elif _is_memory_write_request(t0) or _is_expand_knowledge_request(t0):
                detail = _extract_after_colon(base_text)
                if not detail:
                    detail = base_text
                wrapper_prompt = (
                    "Prepare a write proposal (requires approval) to persist the following into canonical memory/knowledge. "
                    "Use intent=memory_write. Params should include a single field 'note' with the raw user text. "
                    f"USER_NOTE: {detail}"
                )
                result = {
                    "text": (
                        "Razumijem. Pripremiću approval-gated prijedlog za upis. "
                        "Ako treba upis u Notion, prvo aktiviraj Notion Ops: 'notion ops aktiviraj'."
                        if not english_output
                        else "Got it. I'll prepare an approval-gated write proposal. If this needs a Notion write, arm Notion Ops first."
                    ),
                    "proposed_commands": [
                        {
                            "command": PROPOSAL_WRAPPER_INTENT,
                            "args": {"prompt": wrapper_prompt},
                            "reason": "Approval-gated memory/knowledge write proposal.",
                            "requires_approval": True,
                            "risk": "LOW",
                            "dry_run": True,
                            "scope": "api_execute_raw",
                        }
                    ],
                }
            elif not snapshot_has_facts and _should_use_kickoff_in_offline_mode(t0):
                result = {"text": _default_kickoff_text(), "proposed_commands": []}
            else:
                if (
                    isinstance(llm_executor_error_diag, dict)
                    and llm_executor_error_diag.get("kind") == "auth"
                ):
                    if english_output:
                        txt = (
                            "LLM authentication failed (401 invalid_api_key). "
                            "Fix OPENAI_API_KEY / OPENAI_API_MODE configuration."
                        )
                    else:
                        txt = (
                            "LLM autentikacija nije uspjela (401 invalid_api_key). "
                            "Provjeri OPENAI_API_KEY / OPENAI_API_MODE konfiguraciju."
                        )
                else:
                    if english_output:
                        txt = (
                            "LLM execution failed (offline.executor_error). "
                            "Check OPENAI_API_KEY / network / OpenAI configuration and retry."
                        )
                    else:
                        txt = (
                            "LLM izvršavanje nije uspjelo (offline.executor_error). "
                            "Provjeri OPENAI_API_KEY / mrežu / OpenAI konfiguraciju i ponovi."
                        )

                result = {"text": txt, "proposed_commands": []}

        text_out = _pick_text(result) or "CEO advisor nije vratio tekstualni output."
        ssot_ok = True
        try:
            if (
                isinstance(snapshot_payload, dict)
                and snapshot_payload.get("available") is False
            ):
                ssot_ok = False
            if not (isinstance(snap_trace, dict) and snap_trace.get("ready") is True):
                ssot_ok = False
        except Exception:
            ssot_ok = False

        if (not ssot_ok) and re.search(r"(?im)^\s*(GOALS|TASKS)\b", text_out or ""):
            text_out = (
                "Nemam SSOT snapshot u ovom trenutku, zato neću navoditi liste ciljeva i zadataka niti tvrditi poslovni status. "
                "Mogu ipak pomoći s planom: napiši cilj, rok i ograničenja."
                if not english_output
                else "I don't have an SSOT snapshot available right now, so I won't list goals or tasks or business status. "
                "I can still help with a plan: share the objective, deadline, and constraints."
            )
        "- NE SMIJEŠ tvrditi status/rizik/blokade ili brojeve ciljeva/taskova ako to nije eksplicitno u snapshot-u; u tom slučaju reci da nije poznato iz snapshot-a i predloži refresh.\n"
        proposed_items = (
            result.get("proposed_commands") if isinstance(result, dict) else None
        )
        proposed = _to_proposed_commands(proposed_items)

        # Enterprise: advisory review over user-provided content is always read-only.
        if advisory_review:
            proposed = []
            proposed_items = []

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

    # Attach OpenAI key fingerprint diagnostics (never the raw key) to help
    # debug reload/child-process env mismatches.
    if use_llm:
        try:
            from services.agent_router.openai_key_diag import get_openai_key_diag

            diag0 = (
                trace.get("llm_gate_diag")
                if isinstance(trace.get("llm_gate_diag"), dict)
                else {}
            )
            diag0.setdefault("openai_key", get_openai_key_diag())
            trace["llm_gate_diag"] = diag0
        except Exception:
            pass

    if (
        isinstance(llm_executor_error_diag, dict)
        and llm_exit_reason == "offline.executor_error"
    ):
        diag = (
            trace.get("llm_gate_diag")
            if isinstance(trace.get("llm_gate_diag"), dict)
            else {}
        )
        # Keep stable keys for debugging this decision point.
        diag.setdefault("kb_ids_used_count", int(kb_ids_used_count))
        diag.setdefault("kb_hits", int(kb_hits))
        diag.setdefault("kb_mode", kb_mode)
        diag.setdefault("fallback_reason", "offline.executor_error")
        for k in ("status", "code", "kind"):
            if k in llm_executor_error_diag:
                diag[k] = llm_executor_error_diag.get(k)
        trace["llm_gate_diag"] = diag

    if llm_exit_reason:
        trace.setdefault("exit_reason", llm_exit_reason)

    if propose_only:
        trace.setdefault("exit_reason", "fallback.propose_only")
        logger.info("[CEO_ADVISOR_EXIT] deterministic.propose_only")

    return _final(
        AgentOutput(
            text=text_out,
            proposed_commands=proposed,
            agent_id="ceo_advisor",
            read_only=True,
            trace=trace,
        )
    )
