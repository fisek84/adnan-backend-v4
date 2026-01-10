import json
from pathlib import Path


def test_decision_outcome_registry_file_shape() -> None:
    """
    Contract (enterprise):
    - If registry file exists, it must be valid JSON with required top-level keys.
    - This test is isolated: it does NOT assume how many records exist because
      other tests/flows may legitimately create more than one record.
    """
    p = Path(".data/decision_outcomes.json")
    if not p.exists():
        # Allowed: no writes executed in this test run.
        return

    d = json.loads(p.read_text(encoding="utf-8"))

    # Required top-level keys
    assert isinstance(d, dict)
    assert "store" in d
    assert "by_approval_id" in d
    assert "by_execution_id" in d
    assert "updated_at" in d

    store = d.get("store") or {}
    assert isinstance(store, dict)

    # Validate record minimal schema for each stored item
    required_keys = (
        "decision_id",
        "execution_id",
        "approval_id",
        "timestamp",
        "recommendation_type",
        "recommendation_summary",
        "accepted",
        "executed",
        "execution_result",
        "owner",
    )

    for _, rec in store.items():
        assert isinstance(rec, dict)
        for k in required_keys:
            assert k in rec
