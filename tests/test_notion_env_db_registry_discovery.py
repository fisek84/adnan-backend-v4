from __future__ import annotations

import pytest


def test_discover_env_db_registry_filters_only_notion_db_vars(
    monkeypatch: pytest.MonkeyPatch,
):
    # Should include only NOTION_* vars ending with _DB_ID or _DATABASE_ID.
    from services.notion_sync_service import NotionSyncService

    monkeypatch.setenv("NOTION_GOALS_DB_ID", "db_goals")
    monkeypatch.setenv("NOTION_TASKS_DATABASE_ID", "db_tasks_preferred")
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "db_tasks_canonical")
    monkeypatch.setenv("NOTION_OPS_ASSISTANT_ID", "asst_should_not_match")
    monkeypatch.setenv("NOTION_SOMETHING_ELSE", "no_suffix")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-should-not-match")

    reg = NotionSyncService._discover_env_db_registry()
    assert isinstance(reg, list)

    by_key = {x.get("db_key"): x for x in reg if isinstance(x, dict)}

    assert "goals" in by_key
    assert by_key["goals"].get("db_id") == "db_goals"

    assert "tasks" in by_key
    # Prefer *_DB_ID over legacy *_DATABASE_ID
    assert by_key["tasks"].get("db_id") == "db_tasks_canonical"
    assert by_key["tasks"].get("env_name") == "NOTION_TASKS_DB_ID"

    # Must NOT include non-db env vars
    assert "ops_assistant" not in by_key
    assert "openai_api_key" not in by_key

    # Must not accidentally include raw env var names
    env_names = {x.get("env_name") for x in reg if isinstance(x, dict)}
    assert "NOTION_OPS_ASSISTANT_ID" not in env_names

    # Keep ordering stable: core keys first when present.
    ordered_keys = [x.get("db_key") for x in reg if isinstance(x, dict)]
    assert ordered_keys[:1] == ["tasks"]


def test_discover_env_db_registry_ignores_empty_values(monkeypatch: pytest.MonkeyPatch):
    from services.notion_sync_service import NotionSyncService

    monkeypatch.setenv("NOTION_EMPTY_DB_ID", "")
    monkeypatch.setenv("NOTION_SPACES_DATABASE_ID", "   ")

    reg = NotionSyncService._discover_env_db_registry()
    assert all(
        (x.get("db_key") not in {"empty", "spaces"}) for x in reg if isinstance(x, dict)
    )


def _by_key(reg: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {x.get("db_key"): x for x in reg if isinstance(x, dict) and x.get("db_key")}


def _clear_tasks_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("NOTION_TASKS_DB_ID", raising=False)
    monkeypatch.delenv("NOTION_TASKS_DATABASE_ID", raising=False)


def test_env_db_registry_only_db_id(monkeypatch: pytest.MonkeyPatch):
    from services.notion_sync_service import NotionSyncService

    _clear_tasks_env(monkeypatch)
    monkeypatch.setenv("NOTION_TASKS_DB_ID", "db_tasks")
    reg = NotionSyncService._discover_env_db_registry()
    tasks = _by_key(reg)["tasks"]
    assert tasks["db_id"] == "db_tasks"
    assert tasks["env_name"] == "NOTION_TASKS_DB_ID"
    assert tasks["source"] == "DB_ID"


def test_env_db_registry_only_database_id(monkeypatch: pytest.MonkeyPatch):
    from services.notion_sync_service import NotionSyncService

    _clear_tasks_env(monkeypatch)
    monkeypatch.setenv("NOTION_TASKS_DATABASE_ID", "db_tasks_legacy")
    reg = NotionSyncService._discover_env_db_registry()
    tasks = _by_key(reg)["tasks"]
    assert tasks["db_id"] == "db_tasks_legacy"
    assert tasks["env_name"] == "NOTION_TASKS_DATABASE_ID"
    assert tasks["source"] == "DATABASE_ID"


def test_env_db_registry_both_set_different_warns_and_prefers_db_id(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    from services.notion_sync_service import NotionSyncService

    # Ensure warn-once guard doesn't leak across test runs/order.
    NotionSyncService._ENV_DB_REGISTRY_CONFLICT_WARNED.clear()

    _clear_tasks_env(monkeypatch)

    monkeypatch.setenv("NOTION_TASKS_DB_ID", "db_tasks")
    monkeypatch.setenv("NOTION_TASKS_DATABASE_ID", "db_tasks_other")

    caplog.set_level("WARNING")
    reg = NotionSyncService._discover_env_db_registry()
    tasks = _by_key(reg)["tasks"]
    assert tasks["db_id"] == "db_tasks"
    assert tasks["env_name"] == "NOTION_TASKS_DB_ID"
    assert any(
        "notion_env_db_registry_conflict" in r.message
        and "TASKS" in r.message
        and "db_tasks" in r.message
        and "db_tasks_other" in r.message
        for r in caplog.records
    )


def test_env_db_registry_both_set_same_no_warning(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    from services.notion_sync_service import NotionSyncService

    NotionSyncService._ENV_DB_REGISTRY_CONFLICT_WARNED.clear()

    _clear_tasks_env(monkeypatch)

    monkeypatch.setenv("NOTION_TASKS_DB_ID", "db_tasks")
    monkeypatch.setenv("NOTION_TASKS_DATABASE_ID", "db_tasks")

    caplog.set_level("WARNING")
    reg = NotionSyncService._discover_env_db_registry()
    tasks = _by_key(reg)["tasks"]
    assert tasks["db_id"] == "db_tasks"
    assert tasks["env_name"] == "NOTION_TASKS_DB_ID"
    assert not any(
        "notion_env_db_registry_conflict" in r.message for r in caplog.records
    )
