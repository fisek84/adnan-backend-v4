from __future__ import annotations

import re
from typing import Literal


Intent = Literal["deliverable", "notion_write", "weekly", "other"]


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

    # ----------------------------
    # A) DELIVERABLE (highest)
    # ----------------------------
    # Concrete artifacts for sales/growth. Keep broad but focused.
    if re.search(
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
        r")\b",
        t,
    ):
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
