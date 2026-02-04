from __future__ import annotations

import pytest


def test_discover_env_db_registry_filters_only_notion_db_vars(
    monkeypatch: pytest.MonkeyPatch,
):
    # Should include only NOTION_* vars ending with _DB_ID or _DATABASE_ID.
    from services.notion_sync_service import NotionSyncService

    monkeypatch.setenv("NOTION_GOALS_DB_ID", "db_goals")
    monkeypatch.setenv("NOTION_TASKS_DATABASE_ID", "db_tasks_preferred")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "db_tasks_ignored")
    monkeypatch.setenv("NOTION_OPS_ASSISTANT_ID", "asst_should_not_match")
    monkeypatch.setenv("NOTION_SOMETHING_ELSE", "no_suffix")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-match")

    reg = NotionSyncService._discover_env_db_registry()
    assert isinstance(reg, list)

    by_key = {x.get("db_key"): x for x in reg if isinstance(x, dict)}

    assert "goals" in by_key
    assert by_key["goals"].get("db_id") == "db_goals"

    assert "tasks" in by_key
    # Prefer *_DATABASE_ID over *_DB_ID
    assert by_key["tasks"].get("db_id") == "db_tasks_preferred"

    # Must NOT include non-db env vars
    assert "ops_assistant" not in by_key
    assert "openai_api_key" not in by_key

    # Must not accidentally include raw env var names
    env_names = {x.get("env_name") for x in reg if isinstance(x, dict)}
    assert "NOTION_OPS_ASSISTANT_ID" not in env_names

    # Keep ordering stable: core keys first when present.
    ordered_keys = [x.get("db_key") for x in reg if isinstance(x, dict)]
    assert ordered_keys[:2] == ["tasks", "projects"] or ordered_keys[:1] == ["tasks"]


def test_discover_env_db_registry_ignores_empty_values(monkeypatch: pytest.MonkeyPatch):
    from services.notion_sync_service import NotionSyncService

    monkeypatch.setenv("NOTION_EMPTY_DB_ID", "")
    monkeypatch.setenv("NOTION_SPACES_DATABASE_ID", "   ")

    reg = NotionSyncService._discover_env_db_registry()
    assert all(
        (x.get("db_key") not in {"empty", "spaces"}) for x in reg if isinstance(x, dict)
    )
