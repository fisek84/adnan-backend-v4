from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


_TASK_HEADING_RE = re.compile(r"(?mi)^\s*Task\s+(?P<num>\d+)\s*$")

# Strict "Kreiraj Task:" blocks (Bosnian UX)
# NOTE: heading must be a standalone line (no inline title), e.g.:
#   Kreiraj Task:
_KREIRAJ_TASK_HEADING_RE = re.compile(r"(?im)^\s*Kreiraj\s+(?:Task|Zadatak)\s*:\s*$")

# Strict keys allowed inside a Kreiraj Task block.
_KREIRAJ_ALLOWED_KEYS = {
    "name",
    "goal",
    "due date",
    "priority",
    "description",
}


def _looks_like_strict_kreiraj_task_block_request(text: str) -> bool:
    """Detect strict multi-line Kreiraj Task blocks.

    We intentionally do NOT treat single-line prompts like:
      "Kreiraj task: Samo jedan task"
    as block batch requests, to preserve single-create_task UX.

    A strict block request requires:
      - at least 1 Kreiraj Task heading line, AND
      - at least 1 strict key line (Name/Goal/Due Date/Priority/Description)
    """

    if not isinstance(text, str) or not text.strip():
        return False

    if not _KREIRAJ_TASK_HEADING_RE.search(text):
        return False

    # Require at least one strict key line somewhere in the prompt.
    return bool(
        re.search(
            r"(?im)^\s*(Name|Goal|Due\s*Date|Priority|Description)\s*:\s+",
            text,
        )
    )


def is_multi_task_block_request(text: str) -> bool:
    """Deterministic detection for pasted multi-task blocks.

    Trigger only when there are 2+ strict heading lines matching:
      ^\s*Task\s+\d+\s*$  (multiline)
    """

    if not isinstance(text, str) or not text.strip():
        return False

    # Support both legacy "Task <n>" pasted blocks and strict "Kreiraj Task:" blocks.
    if len(_TASK_HEADING_RE.findall(text)) >= 2:
        return True

    # Strict blocks should route deterministically as batch_request even with 1 block,
    # but only when it's truly a multi-line block form (keys present).
    if _looks_like_strict_kreiraj_task_block_request(text):
        return True

    return False


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


def _truncate_inline_kv_leaks(value: str, *, current_key: str) -> str:
    """Prevent inline KV segments from leaking into a field value.

    Example bad line:
      Name: X Goal: Y Due Date: 2026-01-01

    We must keep Name strictly as "X" and ignore the rest.
    """

    v = (value or "").strip()
    if not v:
        return v

    # Look for other key tokens that should never be part of this value.
    other_keys = ["Name", "Goal", "Due Date", "Priority", "Description"]
    # Current key should not truncate on itself.
    ck = (current_key or "").strip().casefold()
    other_keys = [k for k in other_keys if k.casefold() != ck]

    # Find earliest occurrence of "<Key>:" inside the value.
    earliest: Optional[int] = None
    for k in other_keys:
        m = re.search(rf"(?i)\b{re.escape(k)}\s*:\s*", v)
        if not m:
            continue
        pos = int(m.start())
        if pos <= 0:
            continue
        if earliest is None or pos < earliest:
            earliest = pos
    if earliest is not None:
        v = v[:earliest].strip()
    return v


@dataclass(frozen=True)
class TaskBlockParsed:
    heading_num: Optional[int]
    heading_title: Optional[str]
    fields: Dict[str, str]


def _segment_task_blocks(text: str) -> List[TaskBlockParsed]:
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")

    # Mode 1: legacy pasted blocks "Task <n>".
    matches = list(_TASK_HEADING_RE.finditer(s))
    if len(matches) >= 2:
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
            blocks.append(
                TaskBlockParsed(heading_num=num, heading_title=None, fields=fields)
            )
        return blocks

    # Mode 2: strict Bosnian blocks "Kreiraj Task:" / "Kreiraj Zadatak:".
    kmatches = list(_KREIRAJ_TASK_HEADING_RE.finditer(s))
    if len(kmatches) < 1:
        return []

    blocks2: List[TaskBlockParsed] = []
    for idx, m in enumerate(kmatches):
        start = m.end()
        end = kmatches[idx + 1].start() if idx + 1 < len(kmatches) else len(s)
        raw_block = s[start:end]
        raw_lines = raw_block.split("\n")
        lines = [ln.rstrip() for ln in raw_lines]

        fields = _parse_kv_blocks(lines)
        # Strictly keep only allowed keys.
        fields = {k: v for k, v in fields.items() if k in _KREIRAJ_ALLOWED_KEYS}
        blocks2.append(
            TaskBlockParsed(heading_num=None, heading_title=None, fields=fields)
        )

    return blocks2


def _field(fields: Dict[str, str], key: str) -> str:
    return (fields.get(key.lower()) or "").strip()


def build_create_task_batch_operations_from_task_blocks(
    text: str,
) -> List[Dict[str, Any]]:
    """Build notion_write batch operations for multi Task blocks.

    Output operations use op_id as stable client_ref (task_<n> when available).
    """

    blocks = _segment_task_blocks(text)
    if not blocks:
        return []

    from services.notion_keyword_mapper import get_notion_field_name  # noqa: PLC0415

    ops: List[Dict[str, Any]] = []
    used_ids: set[str] = set()

    from services.coo_translation_service import COOTranslationService  # noqa: PLC0415

    for i, blk in enumerate(blocks, start=1):
        fields = blk.fields or {}

        name_raw = _field(fields, "name")
        name_raw = _truncate_inline_kv_leaks(name_raw, current_key="name")
        name = _clean_title(name_raw)
        if not name:
            # Deterministic fallback: prefer heading title (for Kreiraj Task: X), else numbered.
            ht = _clean_title(str(getattr(blk, "heading_title", None) or ""))
            name = ht or f"Task {i}"

        desc = _strip_outer_quotes(_field(fields, "description"))
        status = _strip_outer_quotes(_field(fields, "status"))
        priority = _strip_outer_quotes(
            _truncate_inline_kv_leaks(
                _field(fields, "priority"), current_key="priority"
            )
        )
        goal_title = _strip_outer_quotes(
            _truncate_inline_kv_leaks(_field(fields, "goal"), current_key="goal")
        )
        project_title = _strip_outer_quotes(_field(fields, "project"))

        due_date_raw = _strip_outer_quotes(
            _truncate_inline_kv_leaks(
                _field(fields, "due date"), current_key="due date"
            )
        )
        deadline_raw = _strip_outer_quotes(_field(fields, "deadline"))

        due_date = (
            COOTranslationService._try_parse_date_to_iso(due_date_raw) or due_date_raw
        )
        deadline = (
            COOTranslationService._try_parse_date_to_iso(deadline_raw) or deadline_raw
        )

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
            ps[get_notion_field_name("ai_agent")] = {
                "type": "people",
                "names": assignees,
            }

        if ps:
            payload["property_specs"] = ps

        op_id = (
            f"task_{blk.heading_num}" if blk.heading_num is not None else f"task_{i}"
        )
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
