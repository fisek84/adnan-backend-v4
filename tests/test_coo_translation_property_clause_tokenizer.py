from __future__ import annotations

from services.coo_translation_service import COOTranslationService


def test_goal_title_does_not_include_priority_status_whitespace_style() -> None:
    svc = COOTranslationService()
    cmd = svc.translate(
        raw_input="Kreiraj cilj: Preseli se u EU za 30 dana. Priority high, Status active.",
        source="user",
        context={"initiator": "ceo"},
    )
    assert cmd is not None
    assert cmd.command == "notion_write"

    specs = cmd.params["property_specs"]
    assert specs["Name"]["text"] == "Preseli se u EU za 30 dana"
    assert specs["Priority"]["name"] == "High"
    assert specs["Status"]["name"] == "Active"


def test_task_title_does_not_include_due_date_clause() -> None:
    svc = COOTranslationService()
    cmd = svc.translate(
        raw_input="Kreiraj task: Spakuj kofere. Due Date 3.3.26, Priority low",
        source="user",
        context={"initiator": "ceo"},
    )
    assert cmd is not None
    assert cmd.command == "notion_write"

    specs = cmd.params["property_specs"]
    assert specs["Name"]["text"] == "Spakuj kofere"
    assert specs["Due Date"]["start"] == "2026-03-03"
    assert specs["Priority"]["name"] == "Low"


def test_colon_style_still_works() -> None:
    svc = COOTranslationService()
    cmd = svc.translate(
        raw_input="create goal: Foo bar, priority: high, status: active",
        source="user",
        context={"initiator": "ceo"},
    )
    assert cmd is not None

    specs = cmd.params["property_specs"]
    assert specs["Name"]["text"] == "Foo bar"
    assert specs["Priority"]["name"] == "High"
    assert specs["Status"]["name"] == "Active"


def test_title_word_status_does_not_truncate_without_clause_value() -> None:
    svc = COOTranslationService()
    cmd = svc.translate(
        raw_input="Kreiraj cilj: Poboljšaj status projekta za Q2.",
        source="user",
        context={"initiator": "ceo"},
    )
    assert cmd is not None

    specs = cmd.params["property_specs"]
    assert specs["Name"]["text"] == "Poboljšaj status projekta za Q2"


def test_due_date_slash_same_day_month_is_deterministic() -> None:
    svc = COOTranslationService()
    cmd = svc.translate(
        raw_input="create task: Slash date, due date 03/03/2026",
        source="user",
        context={"initiator": "ceo"},
    )
    assert cmd is not None

    specs = cmd.params["property_specs"]
    assert specs["Due Date"]["start"] == "2026-03-03"
