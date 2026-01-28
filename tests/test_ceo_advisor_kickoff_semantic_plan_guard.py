import asyncio
from dataclasses import dataclass

import pytest


@dataclass
class DummyAgentInput:
    message: str
    snapshot: dict
    metadata: dict


@pytest.mark.parametrize(
    "text",
    [
        "plan",
        "biznis plan",
        "imam plan za prodaju",
    ],
)
def test_semantic_plan_word_does_not_trigger_kickoff_or_proposals(monkeypatch, text):
    from services.ceo_advisor_agent import (
        _should_use_kickoff_in_offline_mode,
        create_ceo_advisor_agent,
    )

    # Regression: plain 'plan*' must never influence kickoff gating.
    assert _should_use_kickoff_in_offline_mode(text) is False

    # Force offline mode (no LLM) and empty snapshot to exercise the kickoff gate.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    agent_input = DummyAgentInput(
        message=text,
        snapshot={},
        metadata={"snapshot_source": "test"},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={}))

    assert out.read_only is True
    assert out.proposed_commands == []
    assert isinstance(out.trace, dict)
    assert out.trace.get("intent") != "kickoff"


@pytest.mark.parametrize(
    "text",
    [
        "weekly plan",
        "sedmični plan",
    ],
)
def test_weekly_or_sedmic_signals_trigger_kickoff_gate(text):
    from services.ceo_advisor_agent import _should_use_kickoff_in_offline_mode

    assert _should_use_kickoff_in_offline_mode(text) is True


def test_explicit_action_command_triggers_kickoff_even_if_contains_plan_word():
    from services.ceo_advisor_agent import _should_use_kickoff_in_offline_mode

    assert (
        _should_use_kickoff_in_offline_mode("kreiraj task: napravi plan prodaje")
        is True
    )


def test_no_side_effects_gate_path_empty_snapshot_biznis_plan(monkeypatch):
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    # Force offline mode (no LLM) to ensure we hit deterministic gate logic.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    agent_input = DummyAgentInput(
        message="biznis plan",
        snapshot={},
        metadata={"snapshot_source": "test"},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={}))

    assert out.read_only is True
    assert out.proposed_commands == []
    assert isinstance(out.trace, dict)
    assert out.trace.get("intent") != "kickoff"
