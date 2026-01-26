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
            "- KB-FIRST: Answer ONLY using the provided KB_CONTEXT below.\n"
            "- DO NOT use general world knowledge.\n"
            "- Do NOT respond with 'Nemam u KB/Memory/Snapshot' when KB_CONTEXT is present; synthesize your answer from KB_CONTEXT.\n"
            "- If you propose actions, put them into proposed_commands but do not execute anything.\n"
            "- NOTION WRITES: Only propose Notion write commands when NOTION_OPS_STATE.armed == true. If armed==false, ask the user to arm Notion Ops ('notion ops aktiviraj') instead of proposing writes.\n"
        )
    else:
        governance = (
            "GOVERNANCE (non-negotiable):\n"
            "- READ-ONLY: no tool calls, no side effects, no external writes.\n"
            "- Answer ONLY from the provided context sections below (IDENTITY, KB_CONTEXT, NOTION_SNAPSHOT, MEMORY_CONTEXT).\n"
            "- DO NOT use general world knowledge. If the answer is not in the provided context, say: 'Nemam u KB/Memory/Snapshot'.\n"
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
    if kb_has_hits:
        notion_txt = "(omitted: KB-first)"
    elif notion_snapshot is not None:
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
        r"(?i)\b(provenance|sources\s+used|status\s+izvora|izvori\s+znanja|sta\s+je\s+koristen\w*|\u0161ta\s+je\s+kori\u0161ten\w*|sta\s+je\s+preskocen\w*|\u0161ta\s+je\s+presko\u010den\w*|za\u0161to\s+presko\u010den\w*|zasto\s+preskocen\w*|trace)\b",
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


def _should_use_kickoff_in_offline_mode(user_text: str) -> bool:
    t = (user_text or "").strip().lower()
    if not t:
        return False
    # If user is asking about goals/tasks/KPIs/planning in an empty state,
    # the deterministic kickoff is a good enterprise-safe fallback.
    # IMPORTANT: don't trigger dashboard/kickoff purely on the word "plan".
    # Otherwise normal questions like "biznis plan" get wrongly routed to GOALS/TASKS.
    wants_targets = bool(
        re.search(r"(?i)\b(cilj\w*|goal\w*|task\w*|zadat\w*|kpi\w*)\b", t)
    )
    wants_planning = bool(re.search(r"(?i)\b(weekly|sedmic\w*)\b", t)) or (
        wants_targets and bool(re.search(r"(?i)\b(plan\w*)\b", t))
    )
    return wants_targets or wants_planning


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

    continue_deliverable = _is_deliverable_continue(base_text)
    intent = classify_intent(base_text)

    def _debug_trace_enabled() -> bool:
        v = (os.getenv("DEBUG_TRACE") or "").strip().lower()
        return v in {"1", "true", "yes", "on"}

    def _is_deliverable_confirm(text: str) -> bool:
        t = " ".join((text or "").strip().lower().split())
        if not t:
            return False
        # Minimal, explicit confirmations only.
        # NOTE: Avoid ambiguous tokens like "ok" / "moze" which can appear in normal questions
        # (e.g., "da li mi agent moze pomoci...") and would incorrectly trigger delegation.
        return bool(
            re.search(
                r"(?i)\b(uradi\s+to|sla\u017eem\s+se|slazem\s+se|proceed|go\s+ahead)\b",
                t,
            )
        )

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

        out.trace = tr
        return out

    # Inicijalizacija goals i tasks
    goals, tasks = _extract_goals_tasks(snapshot_payload)

    # LLM gate variables and logging
    propose_only = _is_propose_only_request(base_text)
    use_llm = not propose_only
    fact_sensitive = _is_fact_sensitive_query(base_text)
    snapshot_has_facts = _snapshot_has_business_facts(snapshot_payload)

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
        try:
            from services.delegation_service import execute_delegation  # noqa: PLC0415
            from services.output_presenters.revenue_growth_presenter import (  # noqa: PLC0415
                to_ceo_report,
            )

            child = await execute_delegation(
                parent_ctx=ctx if isinstance(ctx, dict) else {},
                target_agent_id="revenue_growth_operator",
                task_text=(base_text or "").strip(),
                parent_agent_input=agent_input,
                delegation_reason="explicit_delegate_request",
            )

            out = AgentOutput(
                text=to_ceo_report(child),
                proposed_commands=[],
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
        except Exception:
            logger.exception(
                "[CEO-ADVISOR] Explicit delegation request failed; falling back to CEO Advisor flow."
            )

    # Generic: "pošalji/delegiraj agentu <agent>".
    target_txt = _extract_delegate_target(base_text)
    if isinstance(target_txt, str) and target_txt.strip():
        target_id = _resolve_agent_id_from_text(target_txt)
        if isinstance(target_id, str) and target_id.strip():
            try:
                from services.delegation_service import execute_delegation  # noqa: PLC0415
                from services.output_presenters.revenue_growth_presenter import (  # noqa: PLC0415
                    to_ceo_report,
                )

                task_text = _delegation_task_text_from_prompt(base_text)
                child = await execute_delegation(
                    parent_ctx=ctx if isinstance(ctx, dict) else {},
                    target_agent_id=target_id.strip(),
                    task_text=task_text,
                    parent_agent_input=agent_input,
                    delegation_reason="explicit_delegate_request",
                )

                txt_out = child.text
                if target_id.strip() == "revenue_growth_operator":
                    txt_out = to_ceo_report(child)

                out = AgentOutput(
                    text=txt_out,
                    proposed_commands=[],
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
            except Exception:
                logger.exception(
                    "[CEO-ADVISOR] Generic delegation request failed; falling back to CEO Advisor flow."
                )
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
    # - deliverable confirm must execute Revenue & Growth Operator (via existing router)
    # - deliverable branch must never emit Notion proposals/toggles

    is_confirm = _is_deliverable_confirm(base_text)
    conv_state = ctx.get("conversation_state") if isinstance(ctx, dict) else None
    pending_deliverable = (
        _extract_last_deliverable_from_conversation_state(conv_state)
        if (is_confirm or continue_deliverable)
        else None
    )

    # Explicit continuation keywords should resume the last deliverable even if
    # the new user message does not contain deliverable keywords.
    if continue_deliverable and pending_deliverable:
        try:
            from services.delegation_service import execute_delegation  # noqa: PLC0415
            from services.output_presenters.revenue_growth_presenter import (  # noqa: PLC0415
                to_ceo_report,
            )

            task_text = (
                (pending_deliverable or "").strip()
                + "\n\nKorisnik traži iteraciju/nastavak: "
                + (base_text or "").strip()
            ).strip()

            child = await execute_delegation(
                parent_ctx=ctx if isinstance(ctx, dict) else {},
                target_agent_id="revenue_growth_operator",
                task_text=task_text,
                parent_agent_input=agent_input,
                delegation_reason="deliverable_continue",
            )

            out = AgentOutput(
                text=to_ceo_report(child),
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace={
                    "intent": "deliverable_continue",
                    "delegated_to": "revenue_growth_operator",
                    "delegation_reason": "deliverable_continue",
                    "fallback_used": "none",
                    "snapshot": snap_trace,
                },
            )

            cid = _conversation_id()
            if isinstance(cid, str) and cid.strip():
                _mark_deliverable_completed(
                    conversation_id=cid.strip(), task_text=pending_deliverable
                )

            return _final(out)
        except Exception:
            logger.exception(
                "[CEO-ADVISOR] Deliverable continuation delegation failed; falling back to CEO Advisor flow."
            )

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
        try:
            from services.delegation_service import execute_delegation  # noqa: PLC0415
            from services.output_presenters.revenue_growth_presenter import (  # noqa: PLC0415
                to_ceo_report,
            )

            child = await execute_delegation(
                parent_ctx=ctx if isinstance(ctx, dict) else {},
                target_agent_id="revenue_growth_operator",
                task_text=pending_deliverable,
                parent_agent_input=agent_input,
                delegation_reason="deliverable_confirmed",
            )

            # CEO returns the *real* child output (no Notion proposals).
            out = AgentOutput(
                text=to_ceo_report(child),
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace={
                    "intent": "deliverable_confirmed",
                    "delegated_to": "revenue_growth_operator",
                    "delegation_reason": "deliverable_confirmed",
                    "fallback_used": "none",
                    "snapshot": snap_trace,
                },
            )

            if _debug_trace_enabled():
                notion_present = bool(
                    isinstance(snapshot_payload, dict) and bool(snapshot_payload)
                )
                kb_hits = 0
                try:
                    gp0 = ctx.get("grounding_pack") if isinstance(ctx, dict) else None
                    gp0 = gp0 if isinstance(gp0, dict) else {}
                    tr2 = gp0.get("trace") if isinstance(gp0.get("trace"), dict) else {}
                    kb_hits = (
                        int(tr2.get("kb_hits") or 0) if isinstance(tr2, dict) else 0
                    )
                except Exception:
                    kb_hits = 0

                tasks_empty = not bool(tasks)
                out.trace["debug_trace"] = {
                    "selected_agent_id": "ceo_advisor",
                    "delegated_to": "revenue_growth_operator",
                    "delegation_reason": "deliverable_confirmed",
                    "fallback_used": "none",
                    "inputs_used": {
                        "tasks_empty": bool(tasks_empty),
                        "kb_hit": bool(kb_hits > 0),
                        "notion_snapshot_present": bool(notion_present),
                    },
                }

            cid = _conversation_id()
            if isinstance(cid, str) and cid.strip():
                _mark_deliverable_completed(
                    conversation_id=cid.strip(), task_text=pending_deliverable
                )

            return _final(out)
        except Exception:
            logger.exception(
                "[CEO-ADVISOR] Deliverable confirmation delegation failed; falling back to CEO Advisor flow."
            )

    if intent == "deliverable" and not is_confirm:
        # Proposal-only prompt: ask the user to confirm execution.
        txt = (
            "Mogu delegirati Revenue & Growth Operatoru da napiše konkretne deliverable-e (email/poruke/sekvence).\n"
            "Ako želiš da uradim to sada, potvrdi: 'uradi to' / 'slažem se'."
            if not english_output
            else "I can delegate to Revenue & Growth Operator to draft the concrete deliverables (emails/messages/sequences).\n"
            "To execute now, confirm: 'proceed' / 'go ahead'."
        )

        out = AgentOutput(
            text=txt,
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={
                "intent": "deliverable_proposal",
                "delegation_target": "revenue_growth_operator",
                "fallback_used": "none",
                "snapshot": snap_trace,
            },
        )

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

    # TRACE_STATUS / provenance query: answer from grounding trace, never from memory governance.
    t_prompt0 = (base_text or "").strip().lower()
    if _is_trace_status_query(t_prompt0):
        tr2 = None
        try:
            tr2 = gp_ctx.get("trace") if isinstance(gp_ctx, dict) else None
        except Exception:
            tr2 = None

        tr2 = tr2 if isinstance(tr2, dict) else {}
        txt = _build_trace_status_text(trace_v2=tr2, english_output=english_output)
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
        and (kb_ids_used_count == 0)
        and (kb_hits == 0)
        and (not snapshot_has_facts)
        and (not _should_use_kickoff_in_offline_mode(t0))
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
        and not snapshot_payload.get("goals")
        and not snapshot_payload.get("tasks")
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
