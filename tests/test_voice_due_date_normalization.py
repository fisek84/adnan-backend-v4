import pytest

from routers.voice_router import _normalize_voice_transcript_for_task_create


def test_voice_due_date_spaced_tokens_normalized_for_task_like_input() -> None:
    s = "create task code 95 status active priority high due date 29 03 2026"
    out = _normalize_voice_transcript_for_task_create(s)
    assert "due date 29.03.2026" in out.lower()


def test_voice_due_date_no_keyword_no_change() -> None:
    s = "create task code 95 status active priority high 29 03 2026"
    out = _normalize_voice_transcript_for_task_create(s)
    assert out == s


def test_voice_due_date_out_of_range_no_change() -> None:
    s = "create task status active due date 99 99 2026"
    out = _normalize_voice_transcript_for_task_create(s)
    assert out == s
