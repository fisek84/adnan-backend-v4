from __future__ import annotations

from typing import Any, Dict

import services.notion_delegation_preview_builder as preview_builder


def test_snapshot_task_to_delegate_preview_shape_and_read_only(monkeypatch):
    called: Dict[str, Any] = {"ok": False}

    def _fake_build_agent_task_from_snapshot(task_item: Any) -> Dict[str, Any]:
        called["ok"] = True
        assert isinstance(task_item, dict)
        return {
            "task_text": "Task: T\n\nSource: U\n\nDetails:\n- status: s\n- due: d\n- owner: o",
            "source_task": {"notion_id": "nid", "url": "U"},
        }

    monkeypatch.setattr(
        preview_builder,
        "build_agent_task_from_snapshot",
        _fake_build_agent_task_from_snapshot,
    )

    task_item = {
        "notion_id": "nid",
        "title": "T",
        "url": "U",
        "fields": {"status": "s", "due": "d", "assigned_to": "o"},
    }

    out = preview_builder.build_delegate_agent_task_preview_from_snapshot(
        task_item=task_item,
        agent_id=" revenue_growth_operator ",
    )

    assert called["ok"] is True

    assert out.get("command") == "delegate_agent_task"
    assert out.get("intent") == "delegate_agent_task"
    assert out.get("read_only") is True
    assert out.get("validated") is False

    params = out.get("params")
    assert isinstance(params, dict)
    assert params.get("agent_id") == "revenue_growth_operator"

    assert isinstance(params.get("task_text"), str)
    source_task = params.get("source_task")
    assert isinstance(source_task, dict)
    assert source_task.get("notion_id") == "nid"
    assert source_task.get("url") == "U"


def test_preview_has_no_side_effect_fields_like_approval_or_execution_id():
    task_item = {
        "notion_id": "nid",
        "title": "T",
        "url": "U",
        "fields": {},
    }

    out = preview_builder.build_delegate_agent_task_preview_from_snapshot(
        task_item=task_item,
        agent_id="agent",
    )

    assert "approval_id" not in out
    assert "execution_id" not in out

    params = out.get("params")
    assert isinstance(params, dict)
    assert "approval_id" not in params
    assert "execution_id" not in params
