import pytest


@pytest.mark.parametrize(
    "case_id, gate_input, expected",
    [
        (
            "T001",
            {
                "current_message": "Objasni mi CAP theorem ukratko.",
                "pending_present": False,
                "prior_meta_intent": None,
                "prior_meta_intent_age_seconds": None,
            },
            {
                "intent_category": "NORMAL_QUESTION",
                "reason_code": "normal.default",
                "allowlist_hit": False,
                "ambiguous_flag": False,
                "current_turn_wins": False,
            },
        ),
        (
            "T002",
            {
                "current_message": "Objasni mi CAP theorem ukratko.",
                "pending_present": True,
                "prior_meta_intent": None,
                "prior_meta_intent_age_seconds": None,
            },
            {
                "intent_category": "NORMAL_QUESTION",
                "reason_code": "normal.current_turn_wins_over_pending",
                "allowlist_hit": False,
                "ambiguous_flag": False,
                "current_turn_wins": True,
            },
        ),
        (
            "T003",
            {
                "current_message": "Ponovi prijedlog.",
                "pending_present": True,
                "prior_meta_intent": None,
                "prior_meta_intent_age_seconds": None,
            },
            {
                "intent_category": "PENDING_PROPOSAL_CONFIRM",
                "reason_code": "pending.confirm.allowlist_hit",
                "allowlist_hit": True,
                "ambiguous_flag": False,
                "current_turn_wins": False,
            },
        ),
        (
            "T004",
            {
                "current_message": "Otkaži prijedlog.",
                "pending_present": True,
                "prior_meta_intent": None,
                "prior_meta_intent_age_seconds": None,
            },
            {
                "intent_category": "PENDING_PROPOSAL_DISMISS",
                "reason_code": "pending.dismiss.allowlist_hit",
                "allowlist_hit": True,
                "ambiguous_flag": False,
                "current_turn_wins": False,
            },
        ),
        (
            "T005",
            {
                "current_message": "Kakvu memoriju koristiš?",
                "pending_present": False,
                "prior_meta_intent": None,
                "prior_meta_intent_age_seconds": None,
            },
            {
                "intent_category": "META_ASSISTANT",
                "reason_code": "meta.anchor.allowlist_hit",
                "allowlist_hit": True,
                "ambiguous_flag": False,
                "current_turn_wins": False,
            },
        ),
        (
            "T006",
            {
                "current_message": "   ",
                "pending_present": False,
                "prior_meta_intent": None,
                "prior_meta_intent_age_seconds": None,
            },
            {
                "intent_category": "AMBIGUOUS",
                "reason_code": "ambiguous.empty_or_whitespace",
                "allowlist_hit": False,
                "ambiguous_flag": True,
                "current_turn_wins": False,
            },
        ),
        (
            "T007",
            {
                "current_message": "?",
                "pending_present": False,
                "prior_meta_intent": None,
                "prior_meta_intent_age_seconds": None,
            },
            {
                "intent_category": "AMBIGUOUS",
                "reason_code": "ambiguous.too_short_no_anchor",
                "allowlist_hit": False,
                "ambiguous_flag": True,
                "current_turn_wins": False,
            },
        ),
        (
            "T008",
            {
                "current_message": "Kako radi governance?",
                "pending_present": True,
                "prior_meta_intent": None,
                "prior_meta_intent_age_seconds": None,
            },
            {
                "intent_category": "META_ASSISTANT",
                "reason_code": "meta.current_turn_wins_over_pending",
                "allowlist_hit": True,
                "ambiguous_flag": False,
                "current_turn_wins": True,
            },
        ),
        (
            "T009",
            {
                "current_message": "?",
                "pending_present": True,
                "prior_meta_intent": None,
                "prior_meta_intent_age_seconds": None,
            },
            {
                "intent_category": "AMBIGUOUS",
                "reason_code": "ambiguous.current_turn_wins_over_pending",
                "allowlist_hit": False,
                "ambiguous_flag": True,
                "current_turn_wins": True,
            },
        ),
        (
            "T010",
            {
                "current_message": "notion ops aktiviraj",
                "pending_present": False,
                "prior_meta_intent": None,
                "prior_meta_intent_age_seconds": None,
            },
            {
                "intent_category": "CONTROL_TURN",
                "reason_code": "control.allowlist_hit",
                "allowlist_hit": True,
                "ambiguous_flag": False,
                "current_turn_wins": False,
            },
        ),
    ],
)
def test_turn_gate_matrix_cases(case_id: str, gate_input: dict, expected: dict) -> None:
    """Regression locks for Block 1 Turn Interpretation Authority Gate.

    This test pins:
      - intent_category
      - reason_code
      - allowlist_hit
      - ambiguous_flag
      - current_turn_wins

    No fuzzy assertions.
    """

    from services.turn_interpretation_authority_gate import (  # noqa: PLC0415
        GateInput,
        evaluate_turn_gate,
    )

    decision = evaluate_turn_gate(GateInput(**gate_input))

    assert decision.intent_category == expected["intent_category"], case_id
    assert decision.reason_code == expected["reason_code"], case_id
    assert decision.allowlist_hit is expected["allowlist_hit"], case_id
    assert decision.ambiguous_flag is expected["ambiguous_flag"], case_id
    assert decision.current_turn_wins is expected["current_turn_wins"], case_id
