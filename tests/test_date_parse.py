from __future__ import annotations

from datetime import date

from services.date_parse import DateParseKind, DateParsingPolicy, parse_date


def _fixed_now() -> date:
    return date(2026, 3, 3)


def test_invalid_calendar_date_rejected_iso() -> None:
    res = parse_date(
        "2026-02-31",
        policy=DateParsingPolicy(),
        now_provider=_fixed_now,
    )
    assert res.iso is None
    assert res.kind == DateParseKind.INVALID
    assert "invalid_calendar_date" in res.issues


def test_ambiguous_dotted_date_returns_no_iso_by_default() -> None:
    res = parse_date(
        "04.05.2026",
        policy=DateParsingPolicy(),
        now_provider=_fixed_now,
    )
    assert res.iso is None
    assert res.kind == DateParseKind.AMBIGUOUS
    assert "ambiguous_dotted_date" in res.issues


def test_relative_keywords_with_deterministic_now_provider() -> None:
    res_today = parse_date(
        "danas",
        policy=DateParsingPolicy(),
        now_provider=_fixed_now,
    )
    assert res_today.iso == "2026-03-03"
    assert res_today.kind == DateParseKind.RELATIVE

    res_tomorrow = parse_date(
        "sutra",
        policy=DateParsingPolicy(),
        now_provider=_fixed_now,
    )
    assert res_tomorrow.iso == "2026-03-04"
    assert res_tomorrow.kind == DateParseKind.RELATIVE

    res_day_after = parse_date(
        "prekosutra",
        policy=DateParsingPolicy(),
        now_provider=_fixed_now,
    )
    assert res_day_after.iso == "2026-03-05"
    assert res_day_after.kind == DateParseKind.RELATIVE


def test_us_dotted_date_requires_policy_opt_in() -> None:
    res_default = parse_date(
        "04.20.2026",
        policy=DateParsingPolicy(),
        now_provider=_fixed_now,
    )
    assert res_default.iso is None
    assert res_default.kind == DateParseKind.INVALID

    res_us = parse_date(
        "04.20.2026",
        policy=DateParsingPolicy(allow_us_dotted=True),
        now_provider=_fixed_now,
    )
    assert res_us.iso == "2026-04-20"
    assert res_us.kind == DateParseKind.ABSOLUTE


def test_allow_us_dotted_does_not_remove_ambiguity() -> None:
    res = parse_date(
        "04.05.2026",
        policy=DateParsingPolicy(allow_us_dotted=True),
        now_provider=_fixed_now,
    )
    assert res.iso is None
    assert res.kind == DateParseKind.AMBIGUOUS
    assert "ambiguous_dotted_date" in res.issues


def test_ambiguous_guessing_policy_can_produce_iso() -> None:
    res = parse_date(
        "04.05.2026",
        policy=DateParsingPolicy(allow_ambiguous_dotted_guess=True),
        now_provider=_fixed_now,
    )
    assert res.iso == "2026-05-04"
    assert res.kind == DateParseKind.ABSOLUTE
    assert "ambiguous_dotted_date" in res.issues
