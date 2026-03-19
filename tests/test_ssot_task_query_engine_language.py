from __future__ import annotations

from datetime import date

from services.ssot_task_query_engine import render_task_query_answer, run_task_query


def test_today_no_tasks_renders_english_when_output_lang_en() -> None:
    # Empty snapshot => no tasks.
    snapshot = {"payload": {"dashboard": {"tasks": []}}}

    res = run_task_query(
        snapshot=snapshot,
        user_message="tasks today",
        today=date(2026, 3, 19),
    )

    out = render_task_query_answer(
        res,
        debug=False,
        render_mode="compact",
        output_lang="en",
    )

    assert out == "No tasks for today."
