from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


_GOAL_HEADING_LOOKAHEAD_RE = re.compile(r"(?i)(?=Kreiraj\s+Cilj\s*:)")
_GOAL_HEADING_RE = re.compile(r"(?im)^\s*Kreiraj\s+Cilj\s*:\s*(?P<title>.*)$")


def is_multi_goal_block_request(text: str) -> bool:
    """Deterministic detection for multi-goal blocks.

    Trigger when there are 2+ instances of the strict heading marker:
      Kreiraj\s+Cilj\s*:

    (case-insensitive)
    """

    if not isinstance(text, str) or not text.strip():
        return False

    return len(re.findall(r"(?i)Kreiraj\s+Cilj\s*:", text)) >= 2


def strip_outer_quotes(value: str) -> str:
    t = (value or "").strip()
    if not t:
        return t

    pairs = [
        ('"', '"'),
        ("'", "'"),
        ("\u201c", "\u201d"),  # “ ”
        ("\u201e", "\u201d"),  # „ ”
        ("\u00ab", "\u00bb"),  # « »
    ]
    for lq, rq in pairs:
        if t.startswith(lq) and t.endswith(rq) and len(t) >= 2:
            return t[1:-1].strip()
    return t


def _clean_title(name: str) -> str:
    t = strip_outer_quotes(name)
    t = re.sub(r"^\s*,\s*", "", t)
    return t.strip()


def _split_assignees(raw: str) -> List[str]:
    s = (raw or "").strip()
    if not s:
        return []
    parts = re.split(r"\s+i\s+|\s+and\s+|[,/&]", s, flags=re.IGNORECASE)
    out: List[str] = []
    for p in parts:
        p2 = re.sub(r"[\s\.,;:]+$", "", (p or "").strip())
        if p2:
            out.append(p2)
    return out


def _parse_kv_blocks(lines: List[str]) -> Dict[str, str]:
    """Parse Key: Value lines.

    - Keys are case-insensitive.
    - Description captures multi-line value until next Key: line.
    """

    out: Dict[str, str] = {}

    i = 0
    current_key: Optional[str] = None
    current_val_lines: List[str] = []

    def flush() -> None:
        nonlocal current_key, current_val_lines
        if current_key is None:
            current_val_lines = []
            return
        val = "\n".join(current_val_lines).strip()
        if val:
            out[current_key] = val
        current_key = None
        current_val_lines = []

    key_re = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 _/\-]{0,60})\s*:\s*(.*)\s*$")

    while i < len(lines):
        ln = lines[i]
        m = key_re.match(ln)
        if m:
            key = (m.group(1) or "").strip().lower()
            val0 = (m.group(2) or "").rstrip()

            flush()

            current_key = key
            current_val_lines = [val0]
            i += 1

            if key in {"description", "opis", "desc"}:
                while i < len(lines):
                    nxt = lines[i]
                    if key_re.match(nxt):
                        break
                    current_val_lines.append(nxt.rstrip())
                    i += 1
                flush()
            else:
                flush()
            continue

        i += 1

    flush()
    return out


@dataclass(frozen=True)
class GoalBlockParsed:
    heading_title: str
    fields: Dict[str, str]


def _segment_goal_blocks(text: str) -> List[GoalBlockParsed]:
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")

    if not is_multi_goal_block_request(s):
        return []

    starts = [m.start() for m in _GOAL_HEADING_LOOKAHEAD_RE.finditer(s)]
    if len(starts) < 2:
        return []

    blocks: List[GoalBlockParsed] = []
    for idx, start in enumerate(starts):
        end = starts[idx + 1] if idx + 1 < len(starts) else len(s)
        raw_block = s[start:end].strip("\n")
        if not raw_block.strip():
            continue

        lines_all = raw_block.split("\n")
        first = lines_all[0] if lines_all else ""
        m0 = _GOAL_HEADING_RE.match(first)
        heading_title = (m0.group("title") if m0 else "") or ""
        heading_title = _clean_title(heading_title)

        # Parse remaining lines as KV.
        lines = [ln.rstrip() for ln in lines_all[1:]]
        fields = _parse_kv_blocks(lines)

        blocks.append(GoalBlockParsed(heading_title=heading_title, fields=fields))

    return blocks


def _field(fields: Dict[str, str], *keys: str) -> str:
    for k in keys:
        v = fields.get(k.lower())
        if isinstance(v, str) and v.strip():
            return v.strip()
    return ""


def build_create_goal_batch_operations_from_goal_blocks(text: str) -> List[Dict[str, Any]]:
    """Build notion_write batch operations for multi Goal blocks."""

    blocks = _segment_goal_blocks(text)
    if not blocks:
        return []

    from services.coo_translation_service import COOTranslationService  # noqa: PLC0415
    from services.notion_schema_registry import NotionSchemaRegistry  # noqa: PLC0415

    # Only include goal properties that exist and are writeable.
    goal_props = (
        NotionSchemaRegistry.DATABASES.get("goals", {}).get("properties", {}) or {}
    )

    def _is_writeable_prop(prop_name: str) -> bool:
        meta = goal_props.get(prop_name)
        if not isinstance(meta, dict):
            return False
        return meta.get("read_only") is not True

    title_to_op_id: Dict[str, str] = {}

    ops: List[Dict[str, Any]] = []

    for i, blk in enumerate(blocks, start=1):
        fields = blk.fields or {}

        name = _clean_title(
            strip_outer_quotes(
                _field(fields, "name", "title", "naziv", "ime", "naslov")
            )
        )
        if not name:
            name = blk.heading_title
        if not name:
            name = f"Goal {i}"

        desc = strip_outer_quotes(_field(fields, "description", "opis", "desc"))
        status = strip_outer_quotes(_field(fields, "status"))
        priority = strip_outer_quotes(_field(fields, "priority", "prioritet"))
        deadline_raw = strip_outer_quotes(_field(fields, "deadline", "rok", "due date"))

        deadline = ""
        if deadline_raw:
            iso = COOTranslationService._try_parse_date_to_iso(deadline_raw)
            deadline = iso or deadline_raw

        assigned_to_raw = strip_outer_quotes(
            _field(fields, "assigned to", "assignee", "owner", "odgovoran")
        )
        assignees = _split_assignees(assigned_to_raw)

        parent_goal = strip_outer_quotes(_field(fields, "parent goal", "parent"))

        payload: Dict[str, Any] = {"title": name}
        if desc:
            payload["description"] = desc
        if status:
            payload["status"] = status
        if priority:
            payload["priority"] = priority
        if deadline:
            payload["deadline"] = deadline

        # property_specs: only include fields that exist and are not read-only.
        ps: Dict[str, Any] = {}

        # Optional selects supported by goals schema.
        type_val = strip_outer_quotes(_field(fields, "type", "tip"))
        if type_val and _is_writeable_prop("Type"):
            ps["Type"] = {"type": "select", "name": type_val}

        level_val = strip_outer_quotes(_field(fields, "level", "nivo"))
        if level_val and _is_writeable_prop("Level"):
            ps["Level"] = {"type": "select", "name": level_val}

        outcome_val = strip_outer_quotes(_field(fields, "outcome", "ishod"))
        if outcome_val and _is_writeable_prop("Outcome"):
            ps["Outcome"] = {"type": "select", "name": outcome_val}

        category_val = strip_outer_quotes(_field(fields, "category", "kategorija"))
        if category_val and _is_writeable_prop("Category"):
            ps["Category"] = {"type": "select", "name": category_val}

        if assignees and _is_writeable_prop("Assigned To"):
            # In goals schema snapshot this is multi_select.
            ps["Assigned To"] = {"type": "multi_select", "names": assignees}

        if ps:
            payload["property_specs"] = ps

        op_id = f"goal_{i}"

        # Parent linking via $op_id refs.
        if parent_goal:
            prior = title_to_op_id.get(parent_goal)
            if prior:
                payload["parent_goal_id"] = f"${prior}"
            else:
                payload["parent_goal_title"] = parent_goal

        title_to_op_id[name] = op_id

        ops.append(
            {
                "op_id": op_id,
                "intent": "create_goal",
                "entity_type": "goal",
                "payload": payload,
            }
        )

    return ops
