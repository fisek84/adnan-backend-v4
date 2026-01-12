# tests/test_outcome_feedback_loop_helpers.py
from __future__ import annotations

from services.outcome_feedback_loop_service import (
    _diff_numeric_kpis,
    _extract_kpis_from_world_state,
    _compute_delta_score_and_risk,
)


def test_extract_kpis_from_world_state_happy_path():
    ws = {"kpis": {"summary": [], "alerts": [], "as_of": "2026-01-01T00:00:00Z"}}
    k, note = _extract_kpis_from_world_state(ws)
    assert k == ws["kpis"]
    assert note == "kpis_from_world_state.kpis"


def test_extract_kpis_from_world_state_not_dict():
    k, note = _extract_kpis_from_world_state(["not", "a", "dict"])
    assert k is None
    assert note == "world_state_snapshot_not_dict"


def test_extract_kpis_from_world_state_missing_or_not_dict():
    k1, note1 = _extract_kpis_from_world_state({})
    assert k1 is None
    assert note1 == "kpis_missing_or_not_dict"

    k2, note2 = _extract_kpis_from_world_state({"kpis": ["nope"]})
    assert k2 is None
    assert note2 == "kpis_missing_or_not_dict"


def test_diff_numeric_kpis_happy_path_common_numeric_keys_only():
    before = {"a": 10, "b": 3.5, "c": "x", "d": True, "e": 1}
    after = {"a": 12, "b": 2.0, "c": "y", "d": False, "e": True}
    out, notes = _diff_numeric_kpis(before=before, after=after)
    assert out == {"a": 2.0, "b": -1.5}
    assert notes == []


def test_diff_numeric_kpis_before_not_dict():
    out, notes = _diff_numeric_kpis(before=None, after={})
    assert out == {}
    assert "kpi_before_not_dict" in notes


def test_diff_numeric_kpis_after_not_dict():
    out, notes = _diff_numeric_kpis(before={}, after=None)
    assert out == {}
    assert "kpi_after_not_dict" in notes


def test_diff_numeric_kpis_no_numeric_common_keys():
    out, notes = _diff_numeric_kpis(before={"a": "x"}, after={"a": "y"})
    assert out == {}
    assert "kpi_no_numeric_common_keys" in notes


def test_compute_delta_score_and_risk_with_missing_before_uses_after_as_baseline_for_score():
    after = {
        "strategic_alignment": {"alignment_score": 80},
        "law_compliance": {"risk_level": "low"},
    }
    delta_score, delta_risk, flags = _compute_delta_score_and_risk(
        alignment_before=None,
        alignment_after=after,
    )
    # before missing -> baseline becomes after score per implementation
    assert delta_score == 0.0
    assert "alignment_before_score_missing" in flags
    # risk mapping low -> 1.0; before missing -> baseline becomes after risk -> delta 0
    assert delta_risk == 0.0
    assert "alignment_before_risk_missing" in flags


def test_compute_delta_score_and_risk_normal_case():
    before = {
        "strategic_alignment": {"alignment_score": 50},
        "law_compliance": {"risk_level": "high"},
    }
    after = {
        "strategic_alignment": {"alignment_score": 70},
        "law_compliance": {"risk_level": "medium"},
    }
    delta_score, delta_risk, flags = _compute_delta_score_and_risk(
        alignment_before=before,
        alignment_after=after,
    )
    assert delta_score == 20.0
    # high(3.0) -> medium(2.0) == -1.0
    assert delta_risk == -1.0
    assert flags == []
