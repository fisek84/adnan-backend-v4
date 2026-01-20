from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional


@dataclass
class ParsedGoalTaskBatch:
    goal_title: str
    goal_deadline: Optional[str]
    tasks: list[dict[str, Any]]
    goal_status: Optional[str] = None
    goal_priority: Optional[str] = None
    goal_assignees: Optional[list[str]] = None


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


def _extract_goal_status_priority(prompt: str) -> tuple[Optional[str], Optional[str]]:
    s = (prompt or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in s.split("\n") if ln.strip()]

    goal_idx = 0
    for i, ln in enumerate(lines):
        if re.search(r"(?i)\b(kreiraj|create)\s+(cilj|goal)\b", ln):
            goal_idx = i
            break

    # Only scan the "goal section" so task status/priority doesn't bleed into the goal.
    end_idx = len(lines)
    for j in range(goal_idx + 1, len(lines)):
        ln = lines[j]
        if re.search(r"(?i)\b(kreiraj|create)\s+(task|zadatak)\b", ln):
            end_idx = j
            break
        if re.match(r"(?i)^\s*(?:task|zadatak)\s*\d*\s*[:\.)\-]", ln):
            end_idx = j
            break
        if re.match(r"(?i)^\s*(zadaci|zadatci|tasks)\b", ln):
            end_idx = j
            break

    goal_block = "\n".join(lines[goal_idx:end_idx]).strip()
    if not goal_block and lines:
        goal_block = lines[0]

    status = None
    m_status = re.search(
        r"(?i)\bstatus\s*(?::|\-|\u2013|\u2014)?\s*([^\n,;]{2,40})", goal_block
    )
    if m_status:
        status = (m_status.group(1) or "").strip().strip(",;")

    priority = None
    m_pri = re.search(
        r"(?i)\bpriorit(?:y|et|i|iy)\s*(?::|\-|\u2013|\u2014)?\s*([^\n,;]{2,40})",
        goal_block,
    )
    if m_pri:
        priority = (m_pri.group(1) or "").strip().strip(",;")

    return status, priority


def _extract_goal_assignees(prompt: str) -> Optional[list[str]]:
    """Extract owner/assignee people hints for the goal from the main prompt.

    Supports phrases like:
      - "owner cilja je adnan@example.com"
      - "assignee for this goal: adnan@example.com, sara@example.com"
    """
    s = (prompt or "").strip()
    if not s:
        return None

    m = re.search(
        r"(?i)\b(assignee|assigned\s+to|owner|project\s+owner|goal\s+owner|nositelj|nosilac|dodijeljen|dodijeljena|odgovoran|odgovorna|responsible|lead|zaduzen|zadu\u017eena)\b\s*[:\-\u2013\u2014]?\s*([^\n\r]+)",
        s,
    )
    if not m:
        return None

    assignee_raw = (m.group(2) or "").strip()
    if not assignee_raw:
        return None

    parts = re.split(r"\s+i\s+|\s+and\s+|[,/&]", assignee_raw)
    assignees: list[str] = []
    for p in parts:
        if not p or not p.strip():
            continue
        token = p.strip()
        # Prefer explicit email-like patterns inside the token
        # Match email-like pattern but do not include trailing punctuation
        m_email = re.search(r"[\w\.-]+@[\w\.-]+", token)
        if m_email:
            val = re.sub(r"[\.,;:]+$", "", m_email.group(0))
        else:
            val = re.sub(r"[\.,;:]+$", "", token)
        val = val.strip()
        if val:
            assignees.append(val)

    return assignees or None


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
            if re.match(r"^\s*(?:[-\u2022])\s+", ln):
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
    ln = re.sub(r"^\s*(?:[-\u2022])\s+", "", ln).strip()
    if not ln:
        return None

    # Title: quoted or before dash
    title = None
    qm = re.search(r"[\"']([^\"']+)[\"']", ln)
    if qm:
        title = (qm.group(1) or "").strip()
    else:
        title = re.split(r"\s+-\s+|\s+\u2014\s+|\s+\u2013\s+", ln, maxsplit=1)[
            0
        ].strip()

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

    # Assignee / owner (people hints)
    assignee_raw: Optional[str] = None
    m_assign = re.search(
        r"(?i)\b(assignee|assigned\s+to|owner|task\s+owner|project\s+owner|nositelj|nosilac|dodijeljen|dodijeljena|odgovoran|odgovorna|responsible|lead|zaduzen|zadu\u017eena)\b\s*[:\-\u2013\u2014]?\s*([^,;]+)",
        ln,
    )
    if m_assign:
        assignee_raw = (m_assign.group(2) or "").strip()

    assignees: list[str] = []
    if assignee_raw:
        parts = re.split(r"\s+i\s+|\s+and\s+|[,/&]", assignee_raw)
        # Strip common trailing punctuation so emails/names are clean
        assignees = [
            re.sub(r"[\.,;:]+$", "", p.strip()) for p in parts if p and p.strip()
        ]

    # Relation hints (goal/project by title)
    goal_title_hint: Optional[str] = None
    project_title_hint: Optional[str] = None

    m_goal = re.search(
        r"(?i)(?:povezan|povezi|povezi|link(?:aj)?|connect|attach)?\s*(?:sa|s|with)?\s*(?:ciljem|cilj|goal)\s*[:\-\u2013\u2014]?\s*([^,;]+)",
        ln,
    )
    if m_goal:
        goal_title_hint = (m_goal.group(1) or "").strip()

    m_project = re.search(
        r"(?i)(?:povezan|povezi|povezi|link(?:aj)?|connect|attach)?\s*(?:sa|s|with)?\s*(?:projektom|projekat|projekt|project)\s*[:\-\u2013\u2014]?\s*([^,;]+)",
        ln,
    )
    if m_project:
        project_title_hint = (m_project.group(1) or "").strip()

    # Strip inline property segments accidentally captured in the title (e.g. ", Status ...")
    title_clean = title
    if isinstance(title_clean, str):
        tl = title_clean.lower()
        if re.search(
            r",\s*(status|priority|due\s*date|deadline|assignee|assigned\s+to|related\s+to)\b",
            tl,
        ):
            title_clean = title_clean.split(",", 1)[0].strip()

    out: dict[str, Any] = {"title": title_clean}
    if due:
        out["deadline"] = due
    if status:
        out["status"] = status
    if priority:
        out["priority"] = priority
    if assignees:
        out["assignees"] = assignees
    if goal_title_hint:
        out["goal_title"] = goal_title_hint
    if project_title_hint:
        out["project_title"] = project_title_hint

    return out


def parse_goal_with_explicit_tasks(text: str) -> Optional[ParsedGoalTaskBatch]:
    """
    Enterprise parser for explicit Goal + Task batch prompts (Bos/Eng).

    Must cover test shapes:
      - "Kreiraj novi cilj ...\nZadaci povezani...\n1. \"X\" - due date: ...\n2. ..."
      - "Kreiraj novi cilj ...\nTask 1: X - due date: ...\nTask 2: ..."
      - single sentence: "... Task: X, due date: ..."
      - heuristic: if prompt contains goal/cilj and task keyword but no explicit list, still yield 1 task
    """
    if not isinstance(text, str):
        return None
    raw = (text or "").strip()
    if not raw:
        return None

    t = raw.replace("\r\n", "\n").replace("\r", "\n")

    # Goal info
    goal_title = _extract_goal_title(t)
    if not goal_title:
        return None

    goal_deadline = _extract_goal_deadline(t)
    goal_status, goal_priority = _extract_goal_status_priority(t)
    goal_assignees = _extract_goal_assignees(t)

    # Task lines -> structured dicts
    task_lines = _iter_task_lines(t)
    tasks: list[dict[str, Any]] = []
    for ln in task_lines:
        parsed = _parse_task_line(ln)
        if isinstance(parsed, dict) and parsed.get("title"):
            tasks.append(parsed)

    # Heuristic fallback (covers "Kreiraj cilj: ADNAN X, I TASK LEZI")
    if not tasks:
        low = t.lower()
        if ("cilj" in low or "goal" in low) and ("task" in low or "zadatak" in low):
            idx_task = low.rfind("task")
            idx_zad = low.rfind("zadatak")
            idx = max(idx_task, idx_zad)
            if idx >= 0:
                tail = (t[idx + 4 :] if idx_task == idx else t[idx + 7 :]).strip()
                tail = tail.strip(" \t\"',.;:")
                if tail:
                    parsed = _parse_task_line(f"Task: {tail}")
                    if isinstance(parsed, dict) and parsed.get("title"):
                        tasks.append(parsed)
                    else:
                        tasks.append({"title": tail.split(",", 1)[0].strip()})

    if not tasks:
        return None

    return ParsedGoalTaskBatch(
        goal_title=goal_title,
        goal_deadline=goal_deadline,
        goal_status=goal_status,
        goal_priority=goal_priority,
        tasks=tasks,
        goal_assignees=goal_assignees,
    )


def build_batch_operations_from_parsed(
    parsed: ParsedGoalTaskBatch,
) -> list[dict[str, Any]]:
    """Convert a ParsedGoalTaskBatch into the standard Notion batch operations format."""

    from services.notion_keyword_mapper import (  # noqa: PLC0415
        get_notion_field_name,
    )

    goal_op_id = "goal_1"

    goal_payload: dict[str, Any] = {
        "title": parsed.goal_title,
    }
    if parsed.goal_deadline:
        goal_payload["deadline"] = parsed.goal_deadline

    if parsed.goal_status:
        goal_payload["status"] = parsed.goal_status
    if parsed.goal_priority:
        goal_payload["priority"] = parsed.goal_priority
    if parsed.goal_assignees:
        ps: dict[str, Any] = goal_payload.get("property_specs") or {}
        if not isinstance(ps, dict):
            ps = {}
        ps[get_notion_field_name("assigned_to")] = {
            "type": "people",
            "names": list(parsed.goal_assignees),
        }
        goal_payload["property_specs"] = ps

    operations: list[dict[str, Any]] = [
        {
            "op_id": goal_op_id,
            "intent": "create_goal",
            "entity_type": "goal",
            "payload": goal_payload,
        }
    ]

    for i, task in enumerate(parsed.tasks, start=1):
        if not isinstance(task, dict):
            continue

        task_payload: dict[str, Any] = {
            "title": str(task.get("title") or "").strip() or f"Task {i}",
            "goal_id": f"${goal_op_id}",
        }

        deadline = task.get("deadline")
        if isinstance(deadline, str) and deadline.strip():
            task_payload["deadline"] = deadline.strip()
        status = task.get("status")
        if isinstance(status, str) and status.strip():
            task_payload["status"] = status.strip()
        priority = task.get("priority")
        if isinstance(priority, str) and priority.strip():
            task_payload["priority"] = priority.strip()

        assignees = task.get("assignees")
        if isinstance(assignees, list) and assignees:
            names = [str(x).strip() for x in assignees if str(x).strip()]
            if names:
                ps: dict[str, Any] = task_payload.get("property_specs") or {}
                if not isinstance(ps, dict):
                    ps = {}
                ps[get_notion_field_name("ai_agent")] = {
                    "type": "people",
                    "names": names,
                }
                task_payload["property_specs"] = ps

        operations.append(
            {
                "op_id": f"task_{i}",
                "intent": "create_task",
                "entity_type": "task",
                "payload": task_payload,
            }
        )

    return operations
