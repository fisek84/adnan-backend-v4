import logging

import pytest

from services.notion_keyword_mapper import NotionKeywordMapper


def test_a_explicit_create_task_simple():
    text = "Kreiraj task: ADNAN X, Status: Active, Priority: Low"
    assert NotionKeywordMapper.detect_intent(text) == "create_task"


def test_b_explicit_create_goal_simple():
    text = "Kreiraj cilj: ADNAN X, Status: Active, Priority: Low"
    assert NotionKeywordMapper.detect_intent(text) == "create_goal"


def test_c_goal_plus_tasks_section_is_batch_request():
    text = "Kreiraj cilj: X\nZadaci:\n1) Kreiraj task: A\n2) Kreiraj task: B"
    assert NotionKeywordMapper.detect_intent(text) == "batch_request"


def test_d_explicit_task_not_overridden_by_goal_property():
    text = "Molim: Kreiraj task: A, Goal: X, Status: Active"
    assert NotionKeywordMapper.detect_intent(text) == "create_task"


def test_e_numbered_prefix_does_not_fall_back_to_create_goal():
    text = "1) Kreiraj task: A, Status: Active"
    intent = NotionKeywordMapper.detect_intent(text)
    assert intent != "create_goal"
    assert intent == "create_task"


def test_detect_intent_debug_trace_when_enabled(monkeypatch, caplog):
    monkeypatch.setenv("DEBUG_INTENT", "1")
    caplog.set_level(logging.DEBUG)

    text = "Molim: Kreiraj task: A, Goal: X, Status: Active"
    assert NotionKeywordMapper.detect_intent(text) == "create_task"

    # Proof that the trace is emitted from the true decision point.
    assert "detect_intent: intent=create_task" in caplog.text


@pytest.mark.parametrize("val", ["", "0", "false", "no"])
def test_detect_intent_no_debug_trace_by_default(monkeypatch, caplog, val):
    if val:
        monkeypatch.setenv("DEBUG_INTENT", val)
    else:
        monkeypatch.delenv("DEBUG_INTENT", raising=False)

    caplog.set_level(logging.DEBUG)
    assert NotionKeywordMapper.detect_intent("Kreiraj task: A") == "create_task"
    assert "detect_intent:" not in caplog.text
