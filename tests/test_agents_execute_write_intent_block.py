import pytest
from unittest.mock import AsyncMock, patch

from ext.agents.router import execute_agent


@pytest.mark.anyio
async def test_agents_execute_blocks_write_intent_when_guard_enabled(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ENABLE_WRITE_INTENT_GUARD", "1")

    payload = {
        "command": "notion_write",
        "payload": {"db_key": "goals", "title": "Test"},
    }

    with patch(
        "ext.agents.router.agent_router.execute",
        new=AsyncMock(return_value={"success": True, "result": {"ok": True}}),
    ) as m_execute:
        result = await execute_agent(payload)

    assert result["success"] is False
    assert result["blocked_by"] == "write_intent_guard"
    assert "write_intent" in str(result.get("reason") or "")
    assert "Use /api/chat or /api/ceo-console/command" in str(
        result.get("message") or ""
    )

    # When blocked, execution must not run
    assert m_execute.call_count == 0


@pytest.mark.anyio
async def test_agents_execute_does_not_block_when_guard_disabled(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("ENABLE_WRITE_INTENT_GUARD", "0")

    payload = {
        "command": "notion_write",
        "payload": {"db_key": "goals", "title": "Test"},
    }

    with patch(
        "ext.agents.router.agent_router.execute",
        new=AsyncMock(return_value={"success": True, "result": {"ok": True}}),
    ) as m_execute:
        result = await execute_agent(payload)

    assert result.get("blocked_by") != "write_intent_guard"
    assert m_execute.call_count == 1
