from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class GroundingPolicy:
    """Deterministic policy for choosing grounding sources.

    Goals:
    - Avoid false positives (e.g. merely mentioning "Notion" or "Memory" must not activate reads)
    - Prefer minimal read-only Notion reads for operational questions
    - Only include memory snapshot when user explicitly asks for memory/audit
    """

    intent: str
    needs_notion: bool
    notion_db_keys: List[str]
    needs_memory_snapshot: bool


_PROVENANCE_RE = re.compile(
    r"(?i)\b(provenance|trace|status\s+izvora|izvori\s+znanja|\bsource(s)?\s+used\b|kori\u0161ten\w*|koristen\w*|presko\u010den\w*|preskocen\w*)\b"
)

_SOURCE_LIST_RE = re.compile(r"(?i)\b(kb\s*/\s*identity\s*/\s*memory\s*/\s*notion)\b")

_MEMORY_AUDIT_RE = re.compile(
    r"(?i)\b(\u0161ta\s+pamti\u0161|sta\s+pamtis|memorij\w*|memory\s+snapshot|audit)\b"
)

_OPERATIONAL_RE = re.compile(
    r"(?i)\b(aktivn\w*\s+(task\w*|zadat\w*)|moji\s+(task\w*|zadac\w*)|koji\s+su\s+mi\s+(task\w*|zadac\w*)|project\w*|projekat\w*|cilj\w*|goal\w*|okr\w*|kpi\w*|pipeline|backlog|sprint|\u0161ta\s+je\s+sljede\u0107\w*|sta\s+je\s+sljede\w*|next\s+step)\b"
)

_ASK_LIST_RE = re.compile(
    r"(?i)\b(poka\u017ei|pokazi|prika\u017ei|prikazi|izlistaj|list|show|pogledaj|pro\u010ditaj|procitaj|which|what\s+are|koji\s+su|\u0161ta\s+je|sta\s+je)\b"
)


def classify_prompt(prompt: str) -> GroundingPolicy:
    t = (prompt or "").strip().lower()
    if not t:
        return GroundingPolicy(
            intent="unknown",
            needs_notion=False,
            notion_db_keys=[],
            needs_memory_snapshot=False,
        )

    # Provenance / trace status has priority over all other source keywords.
    if _PROVENANCE_RE.search(t) or _SOURCE_LIST_RE.search(t):
        return GroundingPolicy(
            intent="trace_status",
            needs_notion=False,
            notion_db_keys=[],
            needs_memory_snapshot=False,
        )

    needs_memory = bool(_MEMORY_AUDIT_RE.search(t))

    operational = bool(_OPERATIONAL_RE.search(t)) and bool(_ASK_LIST_RE.search(t))

    notion_db_keys: List[str] = []
    if operational:
        # Default to tasks-first minimal viable context.
        if re.search(r"(?i)\b(task\w*|zadat\w*)\b", t):
            notion_db_keys.append("tasks")
        if re.search(r"(?i)\b(project\w*|projekat\w*)\b", t):
            notion_db_keys.append("projects")
        if re.search(r"(?i)\b(cilj\w*|goal\w*|okr\w*|kpi\w*)\b", t):
            notion_db_keys.append("goals")

        if not notion_db_keys:
            notion_db_keys = ["tasks"]

        # Ensure deterministic priority and uniqueness.
        ordered = [k for k in ("tasks", "projects", "goals") if k in notion_db_keys]
        notion_db_keys = ordered

    return GroundingPolicy(
        intent="operational" if operational else "general",
        needs_notion=bool(operational),
        notion_db_keys=notion_db_keys,
        needs_memory_snapshot=bool(needs_memory),
    )
