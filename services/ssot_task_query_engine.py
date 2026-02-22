from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Optional, Tuple


@dataclass(frozen=True)
class SSOTQueryResult:
    query_type: str
    all_tasks: List[Dict[str, Any]]
    filtered_tasks: List[Dict[str, Any]]
    filtered_goals: List[Dict[str, Any]]
    stats: Dict[str, Any]


def _norm_bhs_ascii(text: str) -> str:
    t = (text or "").lower()
    return (
        t.replace("č", "c")
        .replace("ć", "c")
        .replace("š", "s")
        .replace("đ", "dj")
        .replace("ž", "z")
    )


def _pick_str(v: Any, default: str = "-") -> str:
    if v is None:
        return default
    if isinstance(v, str):
        s = v.strip()
        return s if s else default
    if isinstance(v, (int, float, bool)):
        return str(v)
    if isinstance(v, dict):
        for k in ("title", "name", "value", "status"):
            if k in v:
                return _pick_str(v.get(k), default=default)
    return default


def _pick_due_iso(v: Any) -> str:
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, dict):
        for k in ("start", "date", "value"):
            if k in v:
                return _pick_due_iso(v.get(k))
    return ""


def _parse_iso_date(due_iso: str) -> Optional[date]:
    s = (due_iso or "").strip()
    if not s:
        return None
    try:
        # Accept YYYY-MM-DD only.
        return date.fromisoformat(s[:10])
    except Exception:
        return None


def _normalize_status(raw_status: str) -> str:
    s = _norm_bhs_ascii(raw_status or "")
    s = re.sub(r"\s+", " ", s).strip()
    if not s:
        return "-"

    # Common synonyms in SSOT snapshots.
    if s in {"not started", "not-started", "not_started"}:
        return "to do"
    if s in {"todo", "to-do"}:
        return "to do"
    if s in {"inprogress", "in-progress"}:
        return "in progress"

    return s


def _is_completed_status(status_norm: str) -> bool:
    s = _normalize_status(status_norm)
    return any(x in s for x in ("done", "completed", "complete"))


def extract_snapshot_payload(snapshot: Any) -> Dict[str, Any]:
    if not isinstance(snapshot, dict):
        return {}
    payload = snapshot.get("payload")
    return payload if isinstance(payload, dict) else snapshot


def snapshot_last_sync(snapshot: Any) -> str:
    if not isinstance(snapshot, dict):
        return "-"
    payload = extract_snapshot_payload(snapshot)

    for src in (snapshot, payload):
        try:
            v = src.get("last_sync") if isinstance(src, dict) else None
            if isinstance(v, str) and v.strip():
                return v.strip()
        except Exception:
            pass
    return "-"


def snapshot_tasks(snapshot: Any) -> List[Dict[str, Any]]:
    payload = extract_snapshot_payload(snapshot)
    dashboard = payload.get("dashboard") if isinstance(payload, dict) else None
    dashboard = dashboard if isinstance(dashboard, dict) else {}

    payload_tasks = payload.get("tasks") if isinstance(payload, dict) else None
    dash_tasks = dashboard.get("tasks") if isinstance(dashboard, dict) else None

    if isinstance(dash_tasks, list) and len(dash_tasks) > 0:
        return [t for t in dash_tasks if isinstance(t, dict)]
    if isinstance(payload_tasks, list) and len(payload_tasks) > 0:
        return [t for t in payload_tasks if isinstance(t, dict)]
    if isinstance(dash_tasks, list):
        return [t for t in dash_tasks if isinstance(t, dict)]
    if isinstance(payload_tasks, list):
        return [t for t in payload_tasks if isinstance(t, dict)]
    return []


def snapshot_goals(snapshot: Any) -> List[Dict[str, Any]]:
    payload = extract_snapshot_payload(snapshot)
    dashboard = payload.get("dashboard") if isinstance(payload, dict) else None
    dashboard = dashboard if isinstance(dashboard, dict) else {}

    payload_goals = payload.get("goals") if isinstance(payload, dict) else None
    dash_goals = dashboard.get("goals") if isinstance(dashboard, dict) else None

    if isinstance(dash_goals, list) and len(dash_goals) > 0:
        return [g for g in dash_goals if isinstance(g, dict)]
    if isinstance(payload_goals, list) and len(payload_goals) > 0:
        return [g for g in payload_goals if isinstance(g, dict)]
    if isinstance(dash_goals, list):
        return [g for g in dash_goals if isinstance(g, dict)]
    if isinstance(payload_goals, list):
        return [g for g in payload_goals if isinstance(g, dict)]
    return []


def normalize_goals(goals: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for it in goals:
        fields = it.get("fields") if isinstance(it.get("fields"), dict) else {}
        goal_id = _pick_str(it.get("id") or fields.get("id"), default="")
        title = _pick_str(it.get("title") or it.get("name") or fields.get("title"))
        status = _pick_str(fields.get("status") or it.get("status"))
        due_iso = _pick_due_iso(fields.get("due") or it.get("due"))
        out.append(
            {
                "id": goal_id,
                "title": title,
                "status": _normalize_status(status),
                "due": due_iso or "-",
            }
        )
    return out


def normalize_tasks(
    tasks: List[Dict[str, Any]],
    *,
    goals_by_id: Optional[Dict[str, str]] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    goals_by_id = goals_by_id or {}

    for it in tasks:
        fields = it.get("fields") if isinstance(it.get("fields"), dict) else {}
        task_id = _pick_str(it.get("id") or fields.get("id"), default="")
        title = _pick_str(
            it.get("title")
            or it.get("name")
            or fields.get("title")
            or fields.get("name")
        )
        status = _pick_str(fields.get("status") or it.get("status"))
        priority = _pick_str(fields.get("priority") or it.get("priority"), default="-")
        due_iso = _pick_due_iso(fields.get("due") or it.get("due"))
        goal_id = _pick_str(it.get("goal_id") or fields.get("goal_id"), default="")
        goal_title = (
            _pick_str(goals_by_id.get(goal_id), default="-") if goal_id else "-"
        )

        out.append(
            {
                "id": task_id,
                "title": title,
                "status": _normalize_status(status),
                "due": due_iso or "-",
                "priority": _normalize_status(priority) if priority != "-" else "-",
                "goal_id": goal_id,
                "goal_title": goal_title,
            }
        )

    return out


def _counts_by_status(tasks_norm: List[Dict[str, Any]]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for t in tasks_norm:
        s = _pick_str(t.get("status"), default="-")
        out[s] = int(out.get(s, 0)) + 1
    return out


def _linked_counts(tasks_norm: List[Dict[str, Any]]) -> Tuple[int, int]:
    linked = 0
    unlinked = 0
    for t in tasks_norm:
        if _pick_str(t.get("goal_id"), default=""):
            linked += 1
        else:
            unlinked += 1
    return linked, unlinked


def classify_task_query(user_message: str) -> str:
    t = _norm_bhs_ascii(user_message or "")
    if not t:
        return "default"

    # Broad task markers.
    has_task = bool(re.search(r"(?i)\b(task|zadat|zadac)\w*\b", t))
    has_goal = bool(re.search(r"(?i)\b(goal|cilj)\w*\b", t))
    has_status_filter = bool(re.search(r"(?i)\b(po\s+statusu|status\s*:)\b", t))
    has_priority_filter = bool(re.search(r"(?i)\b(po\s+prioritetu|priority\s*:)\b", t))

    # If the user explicitly talks about goals (and not tasks), don't route to task engine.
    if has_goal and not has_task:
        return "none"

    # Allow explicit filters even if the word "task" isn't present (e.g. "po statusu: Not Started").
    if not (has_task or has_status_filter or has_priority_filter):
        return "none"

    if re.search(r"(?i)\b(svi|sve)\b.*\b(task|zadat|zadac)\w*\b", t) or re.search(
        r"(?i)\b(prikazi|poka(z|ž)i|listaj)\b.*\b(sve|svi)\b", t
    ):
        return "all"

    if re.search(r"(?i)\b(danas|today)\b", t):
        return "today"

    if re.search(r"(?i)\b(overdue|kasn|zakasn)\w*\b", t):
        return "overdue"

    if has_status_filter:
        return "by_status"

    if has_priority_filter:
        return "by_priority"

    # Default task listing/state question.
    if re.search(r"(?i)\b(koji|koje)\b.*\b(task|zadat|zadac)\w*\b", t) or re.search(
        r"(?i)\b(prikazi|poka(z|ž)i|navedi|lista(j)?)\b.*\b(task|zadat|zadac)\w*\b",
        t,
    ):
        return "default"

    # If user merely mentions tasks (often advisory), do not hijack to deterministic listing.
    return "none"


def _extract_status_filter(user_message: str) -> str:
    t = (user_message or "").strip()
    if not t:
        return ""

    # Accept patterns like "po statusu: Not Started" or "status: done"
    m = re.search(r"(?i)(?:po\s+statusu\s*:?|status\s*:)\s*([^\n\r]{1,40})", t)
    if not m:
        return ""
    raw = (m.group(1) or "").strip()
    raw = re.split(r"[\|,;]", raw, maxsplit=1)[0].strip()
    return _normalize_status(raw)


def _extract_priority_filter(user_message: str) -> str:
    t = (user_message or "").strip()
    if not t:
        return ""

    m = re.search(r"(?i)(?:po\s+prioritetu\s*:?|priority\s*:)\s*([^\n\r]{1,40})", t)
    if not m:
        return ""
    raw = (m.group(1) or "").strip()
    raw = re.split(r"[\|,;]", raw, maxsplit=1)[0].strip()
    return _normalize_status(raw)


def run_task_query(
    *,
    snapshot: Any,
    user_message: str,
    today: Optional[date] = None,
) -> SSOTQueryResult:
    today = today or date.today()

    goals_raw = snapshot_goals(snapshot)
    goals_norm = normalize_goals(goals_raw)
    goals_by_id: Dict[str, str] = {
        _pick_str(g.get("id"), default=""): _pick_str(g.get("title"))
        for g in goals_norm
    }
    goals_by_id = {k: v for k, v in goals_by_id.items() if k}

    tasks_raw = snapshot_tasks(snapshot)
    tasks_norm = normalize_tasks(tasks_raw, goals_by_id=goals_by_id)

    query_type = classify_task_query(user_message)

    filtered: List[Dict[str, Any]] = list(tasks_norm)

    if query_type == "all":
        filtered = list(tasks_norm)
    elif query_type == "today":
        filtered = [
            t
            for t in tasks_norm
            if _parse_iso_date(_pick_str(t.get("due"), default="")) == today
        ]
    elif query_type == "overdue":
        out0: List[Dict[str, Any]] = []
        for t in tasks_norm:
            d = _parse_iso_date(_pick_str(t.get("due"), default=""))
            if d is None:
                continue
            if d >= today:
                continue
            if _is_completed_status(_pick_str(t.get("status"), default="")):
                continue
            out0.append(t)
        filtered = out0
    elif query_type == "by_status":
        wanted = _extract_status_filter(user_message)
        if wanted in {"not started", "to do"}:
            wanted = "to do"
        if wanted:
            filtered = [
                t
                for t in tasks_norm
                if _normalize_status(_pick_str(t.get("status"), default="")) == wanted
            ]
    elif query_type == "by_priority":
        wanted = _extract_priority_filter(user_message)
        if wanted:
            filtered = [
                t
                for t in tasks_norm
                if _normalize_status(_pick_str(t.get("priority"), default="")) == wanted
            ]
    elif query_type == "default":
        filtered = list(tasks_norm[:5])

    # Stable ordering for time-based views.
    def _sort_key(it: Dict[str, Any]) -> Tuple[int, str, str]:
        due = _parse_iso_date(_pick_str(it.get("due"), default=""))
        due_ord = due.toordinal() if due else 99999999
        return (due_ord, _pick_str(it.get("status")), _pick_str(it.get("title")))

    if query_type in {"today", "overdue", "all", "by_status", "by_priority"}:
        filtered = sorted(filtered, key=_sort_key)

    counts = _counts_by_status(tasks_norm)
    linked, unlinked = _linked_counts(tasks_norm)

    stats: Dict[str, Any] = {
        "snapshot_tasks_count": int(len(tasks_norm)),
        "snapshot_goals_count": int(len(goals_norm)),
        "counts_by_status": counts,
        "linked_to_goals_count": int(linked),
        "unlinked_count": int(unlinked),
        "today": today.isoformat(),
        "last_sync": snapshot_last_sync(snapshot),
    }

    return SSOTQueryResult(
        query_type=query_type,
        all_tasks=tasks_norm,
        filtered_tasks=filtered,
        filtered_goals=goals_norm,
        stats=stats,
    )


def render_task_query_answer(res: SSOTQueryResult) -> str:
    snapshot_tasks_count = int(res.stats.get("snapshot_tasks_count") or 0)
    last_sync = _pick_str(res.stats.get("last_sync"), default="-")

    lines: List[str] = [
        f"SSOT: snapshot_tasks_count={snapshot_tasks_count}, last_sync={last_sync}",
        "",
    ]

    qt = res.query_type

    if qt == "today" and not res.filtered_tasks:
        lines.append("Nema taskova za danas.")
        today = _parse_iso_date(_pick_str(res.stats.get("today"), default=""))
        today = today or date.today()

        upcoming: List[Dict[str, Any]] = []
        for t in res.all_tasks:
            d = _parse_iso_date(_pick_str(t.get("due"), default=""))
            if d is None:
                continue
            if d <= today:
                continue
            if _is_completed_status(_pick_str(t.get("status"), default="")):
                continue
            upcoming.append(t)

        upcoming = sorted(
            upcoming,
            key=lambda it: (
                _parse_iso_date(_pick_str(it.get("due"), default="")) or date.max,
                _pick_str(it.get("title")),
            ),
        )

        lines.append("")
        lines.append("Sljedeća 3 nadolazeća taska:")
        for i, t in enumerate(upcoming[:3], start=1):
            title = _pick_str(t.get("title"))
            status = _pick_str(t.get("status"))
            due = _pick_str(t.get("due"))
            priority = _pick_str(t.get("priority"))
            goal_title = _pick_str(t.get("goal_title"))
            lines.append(f"{i}) {title} | {status} | {due} | {priority} | {goal_title}")

        return "\n".join(lines).strip()

    if qt == "all":
        lines.append("TASKS (all)")
    elif qt == "default":
        lines.append("TASKS (top 5)")
    elif qt == "overdue":
        lines.append("TASKS (overdue)")
    elif qt == "today":
        lines.append("TASKS (today)")
    elif qt == "by_status":
        lines.append("TASKS (by status)")
    elif qt == "by_priority":
        lines.append("TASKS (by priority)")
    else:
        lines.append("TASKS")

    for i, t in enumerate(res.filtered_tasks, start=1):
        title = _pick_str(t.get("title"))
        status = _pick_str(t.get("status"))
        due = _pick_str(t.get("due"))
        priority = _pick_str(t.get("priority"))
        goal_title = _pick_str(t.get("goal_title"))
        lines.append(f"{i}) {title} | {status} | {due} | {priority} | {goal_title}")

    return "\n".join(lines).strip()
