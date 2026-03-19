from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple


def _is_english_output(output_lang: Optional[str]) -> bool:
    raw = str(output_lang or "").strip().lower()
    return raw.startswith("en")


def _t(output_lang: Optional[str], key: str, **kwargs: Any) -> str:
    en = _is_english_output(output_lang)

    # Keep this minimal and local to this engine (no global i18n refactor).
    table_en = {
        "yes": "Yes.",
        "no": "No.",
        "phase_a_active": "{ans} We currently have {n} active tasks.",
        "phase_a_total": "{ans} We currently have {n} tasks in the system.",
        "phase_a_count": "{n}. Total tasks: {n}.",
        "phase_a_head_none": "We currently have no tasks.",
        "phase_a_head_none_active": "There are currently no active tasks.",
        "phase_a_head_active": "We currently have {n} active tasks.",
        "phase_a_by_status": "By status: {tail}.",
        "no_upcoming": "No upcoming tasks.",
        "no_today": "No tasks for today.",
        "next_upcoming_3": "Next 3 upcoming tasks:",
        "no_tasks": "No tasks.",
        "shown_more": "Showing {shown} of {total}; say 'continue' for the next page.",
        "shown_all": "Showing {shown} of {total}.",
    }

    table_bs = {
        "yes": "Da.",
        "no": "Ne.",
        "phase_a_active": "{ans} Trenutno imamo {n} aktivnih zadataka.",
        "phase_a_total": "{ans} Trenutno imamo {n} zadataka u sistemu.",
        "phase_a_count": "{n}. Ukupno imamo {n} zadataka.",
        "phase_a_head_none": "Trenutno nemamo nijedan zadatak.",
        "phase_a_head_none_active": "Trenutno nema aktivnih zadataka.",
        "phase_a_head_active": "Trenutno imamo {n} aktivnih zadataka.",
        "phase_a_by_status": "Po statusu: {tail}.",
        "no_upcoming": "Nema nadolazećih taskova.",
        "no_today": "Nema taskova za danas.",
        "next_upcoming_3": "Sljedeća 3 nadolazeća taska:",
        "no_tasks": "Nema taskova.",
        "shown_more": "Prikazano {shown} od {total}; reci 'nastavi' za sljedeću stranicu.",
        "shown_all": "Prikazano {shown} od {total}.",
    }

    table = table_en if en else table_bs
    tmpl = table.get(key)
    if not isinstance(tmpl, str):
        tmpl = table_bs.get(key) or ""
    try:
        return str(tmpl).format(**kwargs)
    except Exception:
        return str(tmpl)


def compute_task_stats(snapshot: Any) -> Dict[str, Any]:
    """Compute minimal, stable task stats from an SSOT snapshot.

    Phase A (TASKS) uses this to answer YES/NO(active), COUNT, and STATUS
    deterministically without listing task titles.
    """

    tasks_raw = snapshot_tasks(snapshot)
    tasks_norm = normalize_tasks(tasks_raw)

    total_count = len(tasks_norm)
    active_count = 0
    for t in tasks_norm:
        st = _pick_str(t.get("status"), default="")
        if not _is_completed_status(st):
            active_count += 1

    return {
        "total_count": int(total_count),
        "active_count": int(active_count),
        "counts_by_status": _counts_by_status(tasks_norm),
    }


def render_tasks_phase_a_answer(
    *,
    spec: Any,
    stats: Dict[str, Any],
    output_lang: Optional[str] = None,
) -> str:
    """Render Phase A TASKS answer in answer-first format.

    spec is expected to be a TaskPhaseASpec-like object with:
      - question_type: YES_NO | COUNT | STATUS
      - active_only: bool (only for YES_NO)
    """

    q = getattr(spec, "question_type", None)
    active_only = bool(getattr(spec, "active_only", False))

    total = int(stats.get("total_count") or 0)
    active = int(stats.get("active_count") or 0)
    counts = (
        stats.get("counts_by_status")
        if isinstance(stats.get("counts_by_status"), dict)
        else {}
    )
    counts = {str(k): int(v) for k, v in counts.items() if isinstance(k, str)}

    if q == "YES_NO":
        if active_only:
            has = active > 0
            ans = _t(output_lang, "yes") if has else _t(output_lang, "no")
            return _t(output_lang, "phase_a_active", ans=ans, n=active)

        has = total > 0
        ans = _t(output_lang, "yes") if has else _t(output_lang, "no")
        return _t(output_lang, "phase_a_total", ans=ans, n=total)

    if q == "COUNT":
        # Contract: must start with a number.
        return _t(output_lang, "phase_a_count", n=total)

    if q == "STATUS":
        # Contract: short conclusion first; no task title list.
        if total <= 0:
            head = _t(output_lang, "phase_a_head_none")
        elif active <= 0:
            head = _t(output_lang, "phase_a_head_none_active")
        else:
            head = _t(output_lang, "phase_a_head_active", n=active)

        if not counts:
            return head

        parts = []
        for k in sorted(counts.keys()):
            parts.append(f"{k}: {counts[k]}")
        tail = ", ".join(parts)
        return f"{head} {_t(output_lang, 'phase_a_by_status', tail=tail)}"

    # Phase A renderer is not defined for LIST (handled by list engine).
    return ""


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
    has_tomorrow = bool(re.search(r"(?i)\b(sutra|tomorrow)\b", t))

    # If the user explicitly talks about goals (and not tasks), don't route to task engine.
    if has_goal and not has_task:
        return "none"

    # Allow explicit filters even if the word "task" isn't present.
    if not (has_task or has_status_filter or has_priority_filter or has_tomorrow):
        return "none"

    if re.search(r"(?i)\b(svi|sve)\b.*\b(task|zadat|zadac)\w*\b", t) or re.search(
        r"(?i)\b(prikazi|poka(z|ž)i|(?:iz)?listaj)\b.*\b(sve|svi)\b", t
    ):
        return "all"

    if re.search(r"(?i)\b(danas|today)\b", t):
        return "today"

    if has_tomorrow:
        return "tomorrow"

    if re.search(r"(?i)\b(overdue|kasn|zakasn)\w*\b", t):
        return "overdue"

    if has_status_filter:
        return "by_status"

    if has_priority_filter:
        return "by_priority"

    # Default task listing/state question.
    if re.search(r"(?i)\b(koji|koje)\b.*\b(task|zadat|zadac)\w*\b", t) or re.search(
        r"(?i)\b(prikazi|poka(z|ž)i|navedi|lista(j)?|(?:iz)?listaj)\b.*\b(task|zadat|zadac)\w*\b",
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
    elif query_type == "tomorrow":
        tomorrow = today + timedelta(days=1)
        filtered = [
            t
            for t in tasks_norm
            if _parse_iso_date(_pick_str(t.get("due"), default="")) == tomorrow
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
        # DATA-only: return full data; presentation decides compact vs full.
        filtered = list(tasks_norm)

    # Stable ordering for time-based views.
    def _sort_key(it: Dict[str, Any]) -> Tuple[int, str, str]:
        due = _parse_iso_date(_pick_str(it.get("due"), default=""))
        due_ord = due.toordinal() if due else 99999999
        return (due_ord, _pick_str(it.get("status")), _pick_str(it.get("title")))

    if query_type in {
        "today",
        "tomorrow",
        "overdue",
    }:
        filtered = sorted(filtered, key=_sort_key)

    counts = _counts_by_status(tasks_norm)
    linked, unlinked = _linked_counts(tasks_norm)

    stats: Dict[str, Any] = {
        "snapshot_tasks_count": int(len(tasks_norm)),
        "snapshot_goals_count": int(len(goals_norm)),
        "filtered_count": int(len(filtered)),
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


def _format_task_line(i: int, t: Dict[str, Any]) -> str:
    title = _pick_str(t.get("title"))
    status = _pick_str(t.get("status"))
    due = _pick_str(t.get("due"))
    priority = _pick_str(t.get("priority"))
    goal_title = _pick_str(t.get("goal_title"))
    return f"{i}) {title} | {status} | {due} | {priority} | {goal_title}"


def _upcoming_tasks(
    *,
    tasks: List[Dict[str, Any]],
    today: date,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    upcoming: List[Dict[str, Any]] = []
    for t in tasks:
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
    return upcoming[: max(0, int(limit))]


def render_task_query_answer(
    res: SSOTQueryResult,
    *,
    debug: bool = False,
    render_mode: str = "compact",
    page: int = 1,
    page_size: int = 20,
    output_lang: Optional[str] = None,
) -> str:
    """Render a user-facing task answer.

    Contract:
      - Normal user text must be clean: no SSOT meta header lines.
      - SSOT meta remains available in `res.stats` (caller can attach to trace).
      - render_mode:
          - compact (default): no upcoming; default queries show top 5
          - full: paged/capped list with continuation hint
          - next_upcoming_on_empty: only show upcoming when today list is empty
          - upcoming: show next 1–3 upcoming when user explicitly asks

    debug flag is reserved for callers; preferred place for meta is trace.
    """

    _ = bool(debug)  # keep param for forward-compat; do not inject meta into text.

    qt = (res.query_type or "").strip() or "default"
    mode = (render_mode or "compact").strip().lower()
    if mode not in {"compact", "full", "next_upcoming_on_empty", "upcoming"}:
        mode = "compact"

    # Compute today's date used for upcoming.
    today_iso = _pick_str(res.stats.get("today"), default="")
    today_d = _parse_iso_date(today_iso) or date.today()

    if mode == "upcoming":
        up = _upcoming_tasks(tasks=res.all_tasks, today=today_d, limit=3)
        if not up:
            return _t(output_lang, "no_upcoming")
        lines = ["TASKS (upcoming)"]
        for i, t in enumerate(up, start=1):
            lines.append(_format_task_line(i, t))
        return "\n".join(lines).strip()

    if qt == "today" and not res.filtered_tasks:
        # Compact: only say there are none.
        if mode == "compact":
            return _t(output_lang, "no_today")

        # next_upcoming_on_empty: show 1–3 upcoming only when today is empty.
        if mode == "next_upcoming_on_empty":
            up = _upcoming_tasks(tasks=res.all_tasks, today=today_d, limit=3)
            lines = [_t(output_lang, "no_today")]
            if up:
                lines.append("")
                lines.append(_t(output_lang, "next_upcoming_3"))
                for i, t in enumerate(up, start=1):
                    lines.append(_format_task_line(i, t))
            return "\n".join(lines).strip()

        # full: still empty for today.
        if mode == "full":
            return _t(output_lang, "no_today")

    header = "TASKS"
    if qt == "all":
        header = "TASKS (all)"
    elif qt == "default":
        header = "TASKS"
    elif qt == "overdue":
        header = "TASKS (overdue)"
    elif qt == "today":
        header = "TASKS (today)"
    elif qt == "tomorrow":
        header = "TASKS (tomorrow)"
    elif qt == "by_status":
        header = "TASKS (by status)"
    elif qt == "by_priority":
        header = "TASKS (by priority)"

    tasks = res.filtered_tasks if isinstance(res.filtered_tasks, list) else []

    # Compact: preserve existing "top 5" behavior for default queries only.
    if mode == "compact" and qt == "default":
        tasks = list(tasks[:5])

    # Full: page/cap (render-only, does not change data).
    shown_from = 0
    shown_to = len(tasks)
    total = len(tasks)
    if mode == "full":
        p = int(page) if isinstance(page, int) else 1
        p = 1 if p < 1 else p
        ps = int(page_size) if isinstance(page_size, int) else 20
        ps = 20 if ps <= 0 else min(ps, 200)
        start = (p - 1) * ps
        end = start + ps
        shown_from = start
        shown_to = min(end, total)
        tasks = list(tasks[start:end])

    if not tasks:
        return _t(output_lang, "no_tasks")

    lines = [header]
    for i, t in enumerate(tasks, start=1 + shown_from):
        lines.append(_format_task_line(i, t))

    if mode == "full":
        if shown_to < total:
            lines.append("")
            lines.append(_t(output_lang, "shown_more", shown=shown_to, total=total))
        else:
            lines.append("")
            lines.append(_t(output_lang, "shown_all", shown=shown_to, total=total))

    return "\n".join(lines).strip()
