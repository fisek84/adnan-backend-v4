from __future__ import annotations

from services.ceo_advisor_agent import (
    _has_explicit_action_for_goal_task,
    _wants_goal,
    _wants_notion_task_or_goal,
    _wants_task,
)


def test_narrative_mentions_do_not_trigger_goal_task_or_notion():
    text = (
        "Moj cilj je da porastem 20% ovaj mjesec. "
        "Imam podcilj za Q1. Taskovi su: outreach, follow-up. "
        "Notion koristim za evidenciju, ali ne tražim da išta upisuješ."
    )

    ok, kind = _has_explicit_action_for_goal_task(text)
    assert ok is False
    assert kind == ""

    assert _wants_goal(text) is False
    assert _wants_task(text) is False
    assert _wants_notion_task_or_goal(text) is False


def test_explicit_commands_trigger_goal_task_and_notion():
    assert _wants_goal("Kreiraj cilj: Povećaj MRR na 10k") is True
    assert _wants_task("Dodaj task: Napiši 3 follow-up poruke") is True
    assert _wants_notion_task_or_goal("U Notion upiši task: Napiši landing") is True

    # Helper kind routing
    assert _has_explicit_action_for_goal_task("Kreiraj cilj: X") == (True, "goal")
    assert _has_explicit_action_for_goal_task("Dodaj task: Y") == (True, "task")
