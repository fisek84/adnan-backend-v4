from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4


@dataclass
class ParsedGoalTaskBatch:
    goal_title: str
    goal_deadline: Optional[str]
    tasks: list[dict[str, Any]]


_DATE_DMY = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")


def _to_iso_date(dmy: str) -> Optional[str]:
    m = _DATE_DMY.search(dmy or "")
    if not m:
        return None
    try:
        day = int(m.group(1))
        month = int(m.group(2))
        year = int(m.group(3))
        return datetime(year, month, day).date().isoformat()
    except Exception:
        return None


def _extract_goal_title(prompt: str) -> Optional[str]:
    s = (prompt or "").strip()
    if not s:
        return None

    # Prefer: pod nazivom "..." / named "..."
    m = re.search(r"(?is)\b(?:pod\s+nazivom|named)\s*[\"']([^\"']+)[\"']", s)
    if m:
        t = (m.group(1) or "").strip()
        if t:
            return t

    # Also accept unquoted: pod nazivom X / named X
    m2 = re.search(r"(?is)\b(?:pod\s+nazivom|named)\s+([^\n\r\.\:]+)", s)
    if m2:
        t = (m2.group(1) or "").strip()
        if t:
            # stop before tasks section tokens if present
            for stop in ("Zadaci", "Zadatci", "Tasks"):
                idx = t.lower().find(stop.lower())
                if idx > 0:
                    t = t[:idx].strip()
                    break
            if t:
                return t

    # Fallbacks: patterns like "Kreiraj cilj: X" / "Create goal X"
    m3 = re.search(
        r"(?is)\b(?:kreiraj|napravi|create)\s+cilj\w*\s*[:\-\u2013\u2014]?\s*([^\n\r\.,]+)",
        s,
    )
    if m3:
        t = (m3.group(1) or "").strip()
        if t:
            return t

    # Ultimate fallback: first quoted string in prompt
    q = re.search(r"(?s)[\"']([^\"']+)[\"']", s)
    if q:
        t = (q.group(1) or "").strip()
        if t:
            return t

    return None


def _extract_goal_deadline(prompt: str) -> Optional[str]:
    s = (prompt or "").strip()
    if not s:
        return None

    # Patterns: "rok do 23.02.2026" / "sa rokom do 23.02.2026" / "deadline 23.02.2026"
    m = re.search(
        r"(?is)\b(?:rok\s+do|sa\s+rokom\s+do|deadline)\s*:?\s*(\d{1,2}\.\d{1,2}\.\d{4})",
        s,
    )
    if m:
        return _to_iso_date(m.group(1) or "")

    return None


def _iter_task_lines(prompt: str) -> list[str]:
    s = prompt or ""
    if not s.strip():
        return []

    # Locate tasks section, if any.
    idx = None
    for token in (
        "Zadaci",
        "Zadatci",
        "Zadaci povezani",
        "Zadatci povezani",
        "Tasks",
        "Tasks linked",
        "Zadaci povezani s ovim ciljem",
        "Zadatci povezani s ovim ciljem",
    ):
        p = s.lower().find(token.lower())
        if p >= 0:
            idx = p
            break

    text = s[idx:] if idx is not None else s

    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    out: list[str] = []
    for ln in lines:
        if re.match(r"^\s*\d+\s*[\.)-]\s+", ln):
            out.append(ln)
            continue
        if re.match(r"^\s*(?:task|zadatak)\s*\d+\s*[:\.)-]\s+", ln, re.IGNORECASE):
            out.append(ln)

    # Bullet list support (dash/bullet)
    if not out:
        for ln in lines:
            if re.match(r"^\s*(?:[-•\u2022])\s+", ln):
                out.append(ln)

    if out:
        return out

    # Inline numbered list support: "Zadaci: 1) ... 2) ..."
    inline = text.replace("\r", " ").replace("\n", " ")
    pattern = re.compile(r"\b\d+\s*[\.)-]\s+[^\d]+?(?=\b\d+\s*[\.)-]\s+|$)")
    for m in pattern.finditer(inline):
        seg = (m.group(0) or "").strip()
        if seg:
            out.append(seg)

    if out:
        return out

    # Inline Task 1: ... Task 2: ... support
    pattern2 = re.compile(
        r"\b(?:task|zadatak)\s*\d+\s*[:\.)-]\s+.*?(?=\b(?:task|zadatak)\s*\d+\s*[:\.)-]\s+|$)",
        re.IGNORECASE,
    )
    for m in pattern2.finditer(inline):
        seg = (m.group(0) or "").strip()
        if seg:
            out.append(seg)

    if out:
        return out

    # Simple "Task: ..." / "Zadatak: ..." segments without numbering
    pattern3 = re.compile(
        r"\b(?:task|zadatak)\s*[:]\s+.*?(?=\b(?:task|zadatak)\s*[:]\s+|$)",
        re.IGNORECASE,
    )
    for m in pattern3.finditer(inline):
        seg = (m.group(0) or "").strip()
        if seg:
            out.append(seg)

    return out


def _parse_task_line(line: str) -> Optional[dict[str, Any]]:
    if not line or not isinstance(line, str):
        return None

    # Strip numbering, Task prefixes or bullet prefix
    ln = re.sub(r"^\s*\d+\s*[\.)-]\s+", "", line).strip()
    ln = re.sub(
        r"^\s*(?:task|zadatak)(?:\s*\d+)?\s*[:\.)-]\s+",
        "",
        ln,
        flags=re.IGNORECASE,
    ).strip()
    ln = re.sub(r"^\s*(?:[-•\u2022])\s+", "", ln).strip()
    if not ln:
        return None

    # Title: quoted or before dash
    title = None
    qm = re.search(r"[\"']([^\"']+)[\"']", ln)
    if qm:
        title = (qm.group(1) or "").strip()
    else:
        title = re.split(r"\s+-\s+|\s+—\s+|\s+–\s+", ln, maxsplit=1)[0].strip()

    if not title:
        return None

    due = None
    m_due = re.search(
        r"(?i)\b(?:due\s*date|rok|deadline)\s*:?\s*(\d{1,2}\.\d{1,2}\.\d{4})", ln
    )
    if m_due:
        due = _to_iso_date(m_due.group(1) or "")

    status = None
    m_status = re.search(r"(?i)\bstatus\s*:?\s*([a-zA-Z_\- ]{2,30})", ln)
    if m_status:
        status = (m_status.group(1) or "").strip().strip(",;")

    priority = None
    m_pri = re.search(r"(?i)\bpriority\s*:?\s*([a-zA-Z_\- ]{2,30})", ln)
    if m_pri:
        priority = (m_pri.group(1) or "").strip().strip(",;")

    out: dict[str, Any] = {"title": title}
    if due:
        out["deadline"] = due
    if status:
        out["status"] = status
    if priority:
        out["priority"] = priority

    return out


def parse_goal_with_explicit_tasks(prompt: str) -> Optional[ParsedGoalTaskBatch]:
    """Detect and parse prompts like:

    - "Kreiraj novi cilj pod nazivom \"X\" sa rokom do 23.02.2026. Zadaci povezani s ovim ciljem: 1. \"A\" - due date: ..."

    Returns None if it does not look like an explicit goal+task list request.
    """
    s = (prompt or "").strip()
    if not s:
        return None

    # Must mention goal + tasks AND have a numbered list.
    has_goal = bool(re.search(r"(?i)\b(cilj\w*|goal\w*)\b", s))
    has_tasks = bool(re.search(r"(?i)\b(zadac\w*|zadat\w*|task\w*)\b", s))
    task_lines = _iter_task_lines(s)

    # Inline "... cilj: X, i task Y" helper when no explicit list was found
    if has_goal and has_tasks and not task_lines:
        m_inline = re.search(
            r"(?is)\b(task|zadatak)\b\s*[:,]?\s*(.+)$",
            s,
        )
        if m_inline:
            rest = (m_inline.group(2) or "").strip()
            if rest:
                # Normalise into a synthetic "Task: ..." line so _parse_task_line can handle it.
                task_lines = [f"Task: {rest}"]
    if not (has_goal and has_tasks and len(task_lines) >= 1):
        return None

    goal_title = _extract_goal_title(s)
    if not goal_title:
        return None

    goal_deadline = _extract_goal_deadline(s)

    tasks: list[dict[str, Any]] = []
    for ln in task_lines:
        t = _parse_task_line(ln)
        if t:
            tasks.append(t)

    if not tasks:
        return None

    return ParsedGoalTaskBatch(
        goal_title=goal_title, goal_deadline=goal_deadline, tasks=tasks
    )


def build_batch_operations_from_parsed(
    parsed: ParsedGoalTaskBatch,
) -> list[dict[str, Any]]:
    goal_op_id = f"goal_{uuid4().hex[:8]}"

    goal_payload: dict[str, Any] = {"title": parsed.goal_title}
    if parsed.goal_deadline:
        goal_payload["deadline"] = parsed.goal_deadline

    ops: list[dict[str, Any]] = [
        {
            "op_id": goal_op_id,
            "intent": "create_goal",
            "payload": goal_payload,
        }
    ]

    for t in parsed.tasks:
        op_id = f"task_{uuid4().hex[:8]}"
        payload = dict(t)
        payload["goal_id"] = f"${goal_op_id}"
        ops.append({"op_id": op_id, "intent": "create_task", "payload": payload})

    return ops
