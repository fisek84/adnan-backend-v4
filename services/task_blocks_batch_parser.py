from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


_TASK_HEADING_RE = re.compile(r"(?mi)^\s*Task\s+(?P<num>\d+)\s*$")


def is_multi_task_block_request(text: str) -> bool:
    """Deterministic detection for pasted multi-task blocks.

    Trigger only when there are 2+ strict heading lines matching:
      ^\s*Task\s+\d+\s*$  (multiline)
    """

    if not isinstance(text, str) or not text.strip():
        return False
    return len(_TASK_HEADING_RE.findall(text)) >= 2


def _strip_outer_quotes(s: str) -> str:
    t = (s or "").strip()
    if not t:
        return t

    # Support ASCII and common Unicode quotes
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
    t = _strip_outer_quotes(name)
    # Guard against legacy normalization that can introduce leading ", "
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

            # Starting a new key: flush previous
            flush()

            # Description may continue across lines until next key
            current_key = key
            current_val_lines = [val0]
            i += 1

            if key == "description":
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
class TaskBlockParsed:
    heading_num: Optional[int]
    fields: Dict[str, str]


def _segment_task_blocks(text: str) -> List[TaskBlockParsed]:
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")

    matches = list(_TASK_HEADING_RE.finditer(s))
    if len(matches) < 2:
        return []

    blocks: List[TaskBlockParsed] = []
    for idx, m in enumerate(matches):
        start = m.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(s)
        num = int(m.group("num")) if m.group("num") else None

        raw_block = s[start:end]
        raw_lines = raw_block.split("\n")
        # Keep blank lines (Description multi-line), but trim right side
        lines = [ln.rstrip() for ln in raw_lines]

        fields = _parse_kv_blocks(lines)
        blocks.append(TaskBlockParsed(heading_num=num, fields=fields))

    return blocks


def _field(fields: Dict[str, str], key: str) -> str:
    return (fields.get(key.lower()) or "").strip()


def build_create_task_batch_operations_from_task_blocks(text: str) -> List[Dict[str, Any]]:
    """Build notion_write batch operations for multi Task blocks.

    Output operations use op_id as stable client_ref (task_<n> when available).
    """

    blocks = _segment_task_blocks(text)
    if not blocks:
        return []

    from services.notion_keyword_mapper import get_notion_field_name  # noqa: PLC0415

    ops: List[Dict[str, Any]] = []
    used_ids: set[str] = set()

    for i, blk in enumerate(blocks, start=1):
        fields = blk.fields or {}

        name = _clean_title(_field(fields, "name"))
        if not name:
            # Deterministic fallback: never use the heading as title
            name = f"Task {i}"

        desc = _strip_outer_quotes(_field(fields, "description"))
        status = _strip_outer_quotes(_field(fields, "status"))
        priority = _strip_outer_quotes(_field(fields, "priority"))
        goal_title = _strip_outer_quotes(_field(fields, "goal"))
        project_title = _strip_outer_quotes(_field(fields, "project"))

        due_date = _strip_outer_quotes(_field(fields, "due date"))
        deadline = _strip_outer_quotes(_field(fields, "deadline"))

        order_raw = _strip_outer_quotes(_field(fields, "order"))
        order_val: Optional[float] = None
        if order_raw:
            try:
                order_val = float(order_raw)
            except Exception:
                order_val = None

        assigned_to_raw = _field(fields, "assigned to")
        assignees = _split_assignees(assigned_to_raw)

        payload: Dict[str, Any] = {
            "title": name,
        }
        if desc:
            payload["description"] = desc
        if status:
            payload["status"] = status
        if priority:
            payload["priority"] = priority

        # Relations: keep titles; executor resolves goal/project titles to IDs.
        if goal_title:
            payload["goal_title"] = goal_title
        if project_title:
            payload["project_title"] = project_title

        # Keep both dates when provided (tasks schema supports both Due Date + Deadline).
        ps: Dict[str, Any] = {}
        if due_date:
            ps[get_notion_field_name("due_date")] = {"type": "date", "start": due_date}
        if deadline:
            ps[get_notion_field_name("deadline")] = {"type": "date", "start": deadline}

        # create_task uses a single params.deadline for its default build; pick one deterministically.
        if deadline:
            payload["deadline"] = deadline
        elif due_date:
            payload["deadline"] = due_date

        if order_val is not None:
            ps[get_notion_field_name("order")] = {"type": "number", "number": order_val}

        if assignees:
            ps[get_notion_field_name("ai_agent")] = {"type": "people", "names": assignees}

        if ps:
            payload["property_specs"] = ps

        op_id = f"task_{blk.heading_num}" if blk.heading_num is not None else f"task_{i}"
        if op_id in used_ids:
            op_id = f"task_{i}"
        used_ids.add(op_id)

        ops.append(
            {
                "op_id": op_id,
                "intent": "create_task",
                "entity_type": "task",
                "payload": payload,
            }
        )

    return ops
