from __future__ import annotations

import re
from typing import Literal


Intent = Literal["deliverable", "notion_write", "weekly", "other"]


_DELIVERABLE_KEYWORDS_RE = re.compile(
    r"(?i)\b("
    r"follow\s*-?up|followup|"
    r"cold\s*email|"
    r"email|e-mail|mail|"
    r"dm|direct\s+message|"
    r"poruk\w*|msg|message\w*|"
    r"outreach|prospect\w*|lead\w*|"
    r"sekvenc\w*|sequence\w*|"
    r"skript\w*|script\w*|"
    r"funnel|pipeline|"
    r"sales\s+plan|prodajn\w*\s+plan|"
    r"linkedin"
    r")\b"
)


_DELIVERABLE_REQUEST_VERBS_RE = re.compile(
    r"(?i)\b("
    # Use stems to cover common inflections (e.g., "pripremiti", "napisati").
    r"napis\w*|"
    r"priprem\w*|"
    r"sastav\w*|"
    r"kreir\w*|"
    r"naprav\w*|"
    r"izrad\w*|"
    r"generis\w*|"
    r"daj\s+mi|"
    r"treba\s+mi|"
    r"hoc\w*\s+da|"
    r"mozes\s+li|mo\u017ee\u0161\s+li|"
    # English verbs ("draft" handled separately to avoid label-like "DRAFT:").
    r"write|create|prepare|generate"
    r")\b"
)


def _has_explicit_deliverable_request(t: str) -> bool:
    """True when the user explicitly requests deliverables.

    Prevents false positives on pasted content that merely *mentions* deliverable words.
    Heuristic: require a request verb/phrase near a deliverable keyword.
    """

    if not t:
        return False

    verb_hits = list(_DELIVERABLE_REQUEST_VERBS_RE.finditer(t))

    # Handle "draft" carefully: a pasted header like "DRAFT:" or "DRAFT (copy/paste)" must
    # not be treated as a user request verb.
    for m in re.finditer(r"(?i)\bdraft\b", t):
        tail = t[m.end() : m.end() + 12]
        if re.match(r"\s*[:\(\[\-]", tail):
            continue
        verb_hits.append(m)

    if not verb_hits:
        return False

    kw_hits = list(_DELIVERABLE_KEYWORDS_RE.finditer(t))
    if not kw_hits:
        return False

    # Proximity window (chars) to keep this deterministic and avoid expensive NLP.
    window = 120
    for v in verb_hits:
        for k in kw_hits:
            if abs(v.start() - k.start()) <= window:
                return True

    return False


def _normalize_text(text: str) -> str:
    t = (text or "").strip().lower()
    if not t:
        return ""

    # Bosnian/Croatian/Serbian latin diacritics -> ascii-ish for matching.
    # Minimal and deterministic; avoids adding deps.
    t = (
        t.replace("č", "c")
        .replace("ć", "c")
        .replace("š", "s")
        .replace("đ", "dj")
        .replace("ž", "z")
    )
    return t


def classify_intent(text: str) -> Intent:
    """Classify top-level orchestration intent.

    SSOT rules:
    - deliverable: concrete sales/growth artifacts (email/DM/follow-up/script/sequence/funnel/sales plan/outreach)
    - notion_write: Notion create/update/delete requests (proposal-only, approval-gated)
    - weekly: ONLY explicit weekly phrases (no generic "plan" triggers)
    - other: everything else
    """

    raw = (text or "").strip()
    t = _normalize_text(raw)
    if not t:
        return "other"

    # Advisory/thinking prompts should not be hijacked into deliverable mode
    # just because the pasted content mentions DM/poruke/email.
    if re.search(
        r"(?i)\b("
        r"procitaj|pro\u010ditaj|"
        r"sta\s+misl\w*|\u0161ta\s+misl\w*|"
        r"reci\s+mi|re\u010di\s+mi|"
        r"komentar\w*|feedback|review|analiz\w*|"
        r"moze\s+li\s+se\s+napraviti\s+plan|"
        r"re\u010di\s+sta\s+dalje|reci\s+sta\s+dalje"
        r")\b",
        t,
    ):
        return "other"

    # ----------------------------
    # A) DELIVERABLE (highest)
    # ----------------------------
    # Concrete artifacts for sales/growth.
    # Guardrail: do NOT treat mere mentions (pasted content) as a deliverable request.
    if _DELIVERABLE_KEYWORDS_RE.search(t) and _has_explicit_deliverable_request(t):
        return "deliverable"

    # ----------------------------
    # B) NOTION WRITE
    # ----------------------------
    # Require explicit Notion mention to avoid hijacking generic "create task" text.
    if "notion" in t:
        if re.search(
            r"(?i)\b(create|kreiraj|napravi|dodaj|update|azuriraj|a\u017euriraj|delete|obrisi|obri\u0161i|izbrisi|izbri\u0161i)\b",
            t,
        ) or re.search(r"(?i)\b(cilj\w*|goal\w*|task\w*|zadat\w*|lead\w*)\b", t):
            return "notion_write"

    # ----------------------------
    # C) WEEKLY / PLANNING (strict)
    # ----------------------------
    # ONLY explicit phrases; do not trigger on generic "plan".
    if re.search(r"(?i)\bweekly\s+plan\b", t):
        return "weekly"

    # Bosnian explicit phrases (normalized diacritics already).
    if re.search(r"(?i)\bprioritet\w*\b", t):
        return "weekly"

    if re.search(r"(?i)\bsedmicn\w*\s+plan\b", t):
        return "weekly"

    if re.search(r"(?i)\bsta\s+da\s+radim\s+ove\s+sedmic\w*\b", t):
        return "weekly"

    # "Next week" explicit phrasing (normalized).
    if re.search(r"(?i)\bsljedec\w*\s+sedmic\w*\b", t):
        return "weekly"
    if re.search(r"(?i)\bnaredn\w*\s+sedmic\w*\b", t):
        return "weekly"
    if re.search(r"(?i)\bove\s+sedmic\w*\b", t) and re.search(r"(?i)\bplanir\w*\b", t):
        return "weekly"

    return "other"
