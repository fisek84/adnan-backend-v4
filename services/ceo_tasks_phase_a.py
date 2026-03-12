from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Optional


TaskPhaseAQuestionType = Literal["YES_NO", "COUNT", "STATUS", "LIST"]


@dataclass(frozen=True)
class TaskPhaseASpec:
    question_type: TaskPhaseAQuestionType
    active_only: bool = False


def _norm_bhs_ascii(text: str) -> str:
    t = (text or "").strip().lower()
    return (
        t.replace("č", "c")
        .replace("ć", "c")
        .replace("š", "s")
        .replace("đ", "dj")
        .replace("ž", "z")
    )


def classify_tasks_phase_a(user_message: str) -> Optional[TaskPhaseASpec]:
    """TASKS-only Phase A classifier (shared by router and ceo_advisor_agent).

    Scope (hard): only tasks questions; only YES_NO / COUNT / STATUS / LIST.
    """

    t = _norm_bhs_ascii(user_message)
    if not t:
        return None

    has_task = bool(re.search(r"(?i)\b(task|taskovi|zadat|zadac)\w*\b", t))
    if not has_task:
        return None

    # Out of Phase A scope: goal-scoped task queries are handled by a deterministic
    # goal-scoped join (tasks filtered by goal_id) in the router.
    if re.search(r"(?i)\b(cilj|goal)\w*\b", t):
        return None

    # Out of Phase A scope: time-scoped task queries (today/tomorrow/overdue/deadlines)
    # are handled by the legacy deterministic task query engine.
    if re.search(
        r"(?i)\b(danas|danasnj\w*|today|sutra|tomorrow|prekosutra|overdue|kasn\w*|juce|yesterday)\b",
        t,
    ) or re.search(r"(?i)\b(rok|deadline|due)\b", t):
        return None

    # LIST: explicit show/list intent.
    if re.search(r"(?i)\b(prikazi|pokazi|poka(z|z)i|izlistaj|listaj|lista)\b", t):
        return TaskPhaseASpec(question_type="LIST")

    # STATUS: explicit status intent.
    if re.search(r"(?i)\b(status|po\s+statusu)\b", t) or re.search(
        r"(?i)\bstatus\s*:\s*", t
    ):
        return TaskPhaseASpec(question_type="STATUS")

    # COUNT: explicit count intent.
    if re.search(r"(?i)\b(koliko|broj)\b", t):
        return TaskPhaseASpec(question_type="COUNT")

    # YES_NO: questions about whether tasks exist, optionally active.
    # Keep narrow to avoid hijacking list-style questions like
    # "Koje zadatke imamo ...?" (handled by legacy list engine).
    if re.search(r"(?i)\b(koji|koje|sta|shta)\b", t):
        return None

    is_yes_no = bool(
        re.search(r"(?i)\b(da\s+li|imamo\s+li|ima\s+li|postoji\s+li)\b", t)
    )
    if is_yes_no and re.search(r"(?i)\b(imamo|ima|postoj)\w*\b", t):
        active_only = bool(re.search(r"(?i)\b(aktivn)\w*\b", t))
        return TaskPhaseASpec(question_type="YES_NO", active_only=active_only)

    return None
