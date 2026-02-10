from __future__ import annotations

from services.snapshot_fields_allowlist import (
    SNAPSHOT_FIELDS_ALLOWLIST,
    allowlist_for_db_key,
    is_basic_only_db_key,
)


def test_allowlist_is_single_ssot_mapping():
    assert isinstance(SNAPSHOT_FIELDS_ALLOWLIST, dict)
    assert "tasks" in SNAPSHOT_FIELDS_ALLOWLIST
    assert "goals" in SNAPSHOT_FIELDS_ALLOWLIST
    assert "projects" in SNAPSHOT_FIELDS_ALLOWLIST
    assert "kpi" in SNAPSHOT_FIELDS_ALLOWLIST


def test_each_known_db_key_has_allowlist_or_basic_only_default():
    # Known keys expected in workspace
    keys = [
        "tasks",
        "goals",
        "projects",
        "kpi",
        "agent_exchange",
        "ai_summary",
        # unknown should default to basic-only
        "some_future_db",
    ]

    for k in keys:
        allow = allowlist_for_db_key(k)
        if allow is None:
            assert is_basic_only_db_key(k) is True
        else:
            assert is_basic_only_db_key(k) is False
            assert isinstance(allow, list)
            assert len(allow) > 0
