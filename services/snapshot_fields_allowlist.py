from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal, Optional


AllowedFieldType = Literal[
    "string",
    "number",
    "boolean",
    "date",
    "select",
    "multi_select",
    "people",
    "relation",
    "kpi_numeric_all",
]


@dataclass(frozen=True)
class FieldSpec:
    out_key: str
    # Candidate Notion property names to look for (case-insensitive exact match)
    names: List[str]
    kind: AllowedFieldType


# SINGLE SOURCE OF TRUTH (SSOT)
# - db_key is lower-case, as produced by NotionSyncService env registry.
# - Only allowlisted fields are exported into snapshot item["fields"].
SNAPSHOT_FIELDS_ALLOWLIST: Dict[str, List[FieldSpec]] = {
    "tasks": [
        FieldSpec("status", ["Status", "State"], "select"),
        FieldSpec(
            "due",
            ["Due", "Due Date", "Deadline", "Target Deadline", "End Date"],
            "date",
        ),
        FieldSpec("priority", ["Priority", "Prio"], "select"),
        FieldSpec(
            "assigned_to",
            ["Assigned", "Assignee", "Owner", "Assigned To"],
            "people",
        ),
        FieldSpec("goal", ["Goal", "Primary Goal", "Goals"], "relation"),
        FieldSpec("project", ["Project", "Projects"], "relation"),
    ],
    "goals": [
        FieldSpec("status", ["Status", "State"], "select"),
        FieldSpec("progress", ["Progress", "%", "Percent"], "number"),
        FieldSpec(
            "due",
            ["Due", "Due Date", "Deadline", "Target Deadline", "End Date"],
            "date",
        ),
        FieldSpec("owner", ["Owner", "Assigned", "Responsible"], "people"),
        FieldSpec("tasks", ["Tasks", "Tasks DB"], "relation"),
        FieldSpec("projects", ["Projects", "Projects DB"], "relation"),
    ],
    "projects": [
        FieldSpec("status", ["Status", "State"], "select"),
        FieldSpec("priority", ["Priority", "Prio"], "select"),
        FieldSpec(
            "target_deadline",
            ["Target Deadline", "Deadline", "Due", "Due Date", "End Date"],
            "date",
        ),
        FieldSpec("progress", ["Progress", "%", "Percent"], "number"),
        FieldSpec("next_step", ["Next Step", "Next", "Next action"], "string"),
        FieldSpec("primary_goal", ["Primary Goal", "Goal"], "relation"),
    ],
    # KPI: period/cycle plus numeric fields (number/formula/rollup that resolve to number)
    "kpi": [
        FieldSpec("period", ["Period", "Week", "Cycle", "Date"], "string"),
        FieldSpec("__numeric__", [], "kpi_numeric_all"),
    ],
    "kpis": [
        FieldSpec("period", ["Period", "Week", "Cycle", "Date"], "string"),
        FieldSpec("__numeric__", [], "kpi_numeric_all"),
    ],
    "agent_exchange": [
        FieldSpec("status", ["Status", "State"], "select"),
        FieldSpec("timestamp", ["Timestamp", "Time", "Date"], "date"),
        FieldSpec("sender", ["Sender", "From"], "string"),
        FieldSpec("recipient", ["Recipient", "To"], "string"),
        FieldSpec("summary", ["Summary", "Message", "Notes"], "string"),
        FieldSpec("tags", ["Tags", "Labels"], "multi_select"),
    ],
    "ai_summary": [
        FieldSpec("status", ["Status", "State"], "select"),
        FieldSpec("timestamp", ["Timestamp", "Time", "Date"], "date"),
        FieldSpec("summary", ["Summary", "AI Summary", "Notes"], "string"),
        FieldSpec("tags", ["Tags", "Labels"], "multi_select"),
    ],
}


def allowlist_for_db_key(db_key: str) -> Optional[List[FieldSpec]]:
    k = (db_key or "").strip().lower()
    if not k:
        return None
    return SNAPSHOT_FIELDS_ALLOWLIST.get(k)


def is_basic_only_db_key(db_key: str) -> bool:
    """Default behavior for unknown db_keys: export basic item without fields."""
    k = (db_key or "").strip().lower()
    if not k:
        return True
    return k not in SNAPSHOT_FIELDS_ALLOWLIST
