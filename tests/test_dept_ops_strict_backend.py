from __future__ import annotations

import json

import pytest

from models.agent_contract import AgentInput, AgentOutput
from services.department_agents import dept_ops_agent


@pytest.mark.anyio
async def test_dept_ops_strict_backend_bypasses_llm(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _llm_called(*_args, **_kwargs):
        raise RuntimeError("LLM called")

    # If strict backend is active, this must never be called.
    monkeypatch.setattr("services.department_agents.create_ceo_advisor_agent", _llm_called)

    out = await dept_ops_agent(
        AgentInput(
            message="DEPT OPS: ops.snapshot_health please",
            preferred_agent_id="dept_ops",
            conversation_id="conv1",
            metadata={"read_only": True},
        ),
        ctx={"grounding_pack": {"kb_retrieved": {"used_entry_ids": ["kb1"]}}},
    )

    assert isinstance(out, AgentOutput)
    assert out.agent_id == "dept_ops"
    assert out.proposed_commands == []

    # JSON-only text
    assert isinstance(out.text, str)
    assert "Summary" not in out.text
    assert "Recommendation" not in out.text

    parsed = json.loads(out.text)
    assert isinstance(parsed, dict)
    assert parsed.get("kind") == "ops.snapshot_health"

    tr = out.trace
    assert isinstance(tr, dict)
    assert tr.get("dept_ops_strict_backend") is True
    assert tr.get("selected_query") == "ops.snapshot_health"
    assert tr.get("selected_by") == "preferred_agent_id"


@pytest.mark.anyio
async def test_dept_ops_non_explicit_keeps_old_behavior(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    async def _dummy_ceo_advisor_agent(*_args, **_kwargs):
        calls["n"] += 1
        return AgentOutput(
            text="dummy",
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={},
        )

    monkeypatch.setattr(
        "services.department_agents.create_ceo_advisor_agent", _dummy_ceo_advisor_agent
    )

    out = await dept_ops_agent(
        AgentInput(message="hello", preferred_agent_id=None, metadata={"read_only": True}),
        ctx={},
    )

    assert calls["n"] == 1, "expected legacy LLM delegation path"
    assert isinstance(out.text, str)
    assert "Summary" in out.text


@pytest.mark.anyio
async def test_dept_ops_strict_backend_query_selection_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _llm_called(*_args, **_kwargs):
        raise RuntimeError("LLM called")

    monkeypatch.setattr("services.department_agents.create_ceo_advisor_agent", _llm_called)

    # 1) KPI
    out = await dept_ops_agent(
        AgentInput(
            message="DEPT OPS: kpi",
            preferred_agent_id=None,
            conversation_id="conv2",
            metadata={"read_only": True},
        ),
        ctx={},
    )
    assert out.trace.get("dept_ops_strict_backend") is True
    assert out.trace.get("selected_by") == "prefix"
    assert out.trace.get("selected_query") == "ops.kpi_weekly_summary_preview"
    assert json.loads(out.text).get("kind") == "ops.kpi_weekly_summary_preview"

    # 2) Snapshot health
    out = await dept_ops_agent(
        AgentInput(
            message="DEPT OPS: snapshot_health",
            preferred_agent_id=None,
            conversation_id="conv3",
            metadata={"read_only": True},
        ),
        ctx={},
    )
    assert out.trace.get("selected_query") == "ops.snapshot_health"
    assert json.loads(out.text).get("kind") == "ops.snapshot_health"

    # 3) Default
    out = await dept_ops_agent(
        AgentInput(
            message="DEPT OPS: bilo šta",
            preferred_agent_id=None,
            conversation_id="conv4",
            metadata={"read_only": True},
        ),
        ctx={},
    )
    assert out.trace.get("selected_query") == "ops.daily_brief"
    assert json.loads(out.text).get("kind") == "ops.daily_brief"
