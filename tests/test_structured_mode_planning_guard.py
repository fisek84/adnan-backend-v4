from __future__ import annotations

from services.ceo_advisor_agent import _needs_structured_snapshot_answer


def test_planning_help_prompt_does_not_trigger_structured_mode():
    # Regression: production prompt was incorrectly forced into GOALS/TASKS dashboard format.
    prompt = (
        "Sljedece sedmice planiram poceti sa 7 dana cilj i taskovi - "
        "mozes li mi pomoci ?"
    )

    assert _needs_structured_snapshot_answer(prompt) is False


def test_mixed_prompts_do_not_trigger_structured_mode():
    bad = [
        "Sljedece sedmice planiram poceti sa 7 dana cilj i taskovi - mozes li mi pomoci?",
        "Možeš li mi pomoći da definisem ciljeve i taskove za 7 dana?",
        "Kako da počnem sa ciljevima i taskovima?",
        "Treba mi pomoć oko plana za ciljeve i taskove (ne listaj stanje).",
        "Plan za narednu sedmicu: ciljevi i taskovi — pomozi.",
        "biznis plan",  # must never route to dashboard
        "business plan",  # must never route to dashboard
    ]
    for prompt in bad:
        assert (
            _needs_structured_snapshot_answer(prompt) is False
        ), f"unexpected structured_mode for: {prompt}"


def test_show_goals_prompt_still_triggers_structured_mode():
    prompt = "Pokaži ciljeve i taskove"
    assert _needs_structured_snapshot_answer(prompt) is True


def test_status_dashboard_prompts_trigger_structured_mode():
    good = [
        "status ciljeva",
        "dashboard ciljevi",
        "snapshot taskova",
        "Top 3 cilja",
        "Top 5 taskova",
        "prioritet taskova",
    ]
    for prompt in good:
        assert (
            _needs_structured_snapshot_answer(prompt) is True
        ), f"expected structured_mode for: {prompt}"
