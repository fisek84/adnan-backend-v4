from __future__ import annotations

from datetime import date

import services.coo_translation_service as cts
from services.coo_translation_service import COOTranslationService


def test_goal_deadline_3_3_26_becomes_iso() -> None:
    svc = COOTranslationService()
    cmd = svc.translate(
        raw_input="create goal: Test goal, deadline: 3.3.26",
        source="user",
        context={"initiator": "ceo"},
    )
    assert cmd is not None
    assert cmd.command == "notion_write"

    specs = cmd.params["property_specs"]
    assert specs["Deadline"]["start"] == "2026-03-03"


def test_task_due_3_3_26_becomes_iso() -> None:
    svc = COOTranslationService()
    cmd = svc.translate(
        raw_input="create task: Test task, due: 3.3.26",
        source="user",
        context={"initiator": "ceo"},
    )
    assert cmd is not None
    assert cmd.command == "notion_write"

    specs = cmd.params["property_specs"]
    assert specs["Due Date"]["start"] == "2026-03-03"


def test_invalid_date_is_omitted() -> None:
    svc = COOTranslationService()

    goal_cmd = svc.translate(
        raw_input="create goal: Bad date, deadline: 31.02.2026",
        source="user",
        context={"initiator": "ceo"},
    )
    assert goal_cmd is not None
    goal_specs = goal_cmd.params["property_specs"]
    assert "Deadline" not in goal_specs

    task_cmd = svc.translate(
        raw_input="create task: Bad date, due: 31.02.2026",
        source="user",
        context={"initiator": "ceo"},
    )
    assert task_cmd is not None
    task_specs = task_cmd.params["property_specs"]
    assert "Due Date" not in task_specs


def test_relative_today(monkeypatch) -> None:
    class _FixedDate(date):
        @classmethod
        def today(cls) -> date:  # type: ignore[override]
            return date(2026, 3, 3)

    monkeypatch.setattr(cts, "date", _FixedDate)

    svc = COOTranslationService()
    cmd = svc.translate(
        raw_input="create task: Today task, due: danas",
        source="user",
        context={"initiator": "ceo"},
    )
    assert cmd is not None
    specs = cmd.params["property_specs"]
    assert specs["Due Date"]["start"] == "2026-03-03"
