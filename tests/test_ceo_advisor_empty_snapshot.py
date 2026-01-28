import asyncio
from dataclasses import dataclass


@dataclass
class DummyAgentInput:
    message: str
    snapshot: dict
    metadata: dict


def test_ceo_advisor_empty_snapshot_is_advisory():
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    agent_input = DummyAgentInput(
        message="Imam prazno stanje, kako da pocnem?",
        snapshot={},
        metadata={"snapshot_source": "test"},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={}))

    assert out.read_only is True
    assert isinstance(out.trace, dict)
    assert isinstance(out.trace.get("snapshot"), dict)
    assert "NEMA DOVOLJNO PODATAKA" not in (out.text or "").upper()
    assert ("?" in (out.text or "")) or ("KRENIMO" in (out.text or "").upper())


def test_ceo_advisor_predlagati_goals_tasks_does_not_use_old_copy(monkeypatch):
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    # Force offline mode (no LLM) to exercise deterministic kickoff path.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    agent_input = DummyAgentInput(
        message="Možeš li predlagati ciljeve i taskove koje ću zapisati u Notion?",
        snapshot={},
        metadata={"snapshot_source": "test"},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={}))

    txt = out.text or ""
    assert out.read_only is True
    assert out.proposed_commands == []
    assert isinstance(out.trace, dict)
    assert isinstance(out.trace.get("snapshot"), dict)
    assert out.trace.get("intent") != "kickoff"
    assert "GOALS (top 3)" not in txt
    assert "TASKS (top 5)" not in txt


def test_ceo_advisor_prepare_prompt_for_goal_subgoal_returns_template(monkeypatch):
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    # Offline mode (no LLM) should still return a useful template.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    agent_input = DummyAgentInput(
        message=(
            "Dali mozes da mi pripremis prompt za kreiraj cilj i potcilj "
            "koji cu poslati Notion ops agentu da upise u notion"
        ),
        snapshot={},
        metadata={"snapshot_source": "test"},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={}))
    txt = out.text or ""

    assert out.read_only is True
    assert isinstance(out.trace, dict)
    assert out.trace.get("prompt_template") is True
    # Should be a template, not the dashboard structured output.
    assert "GOALS (top 3)" not in txt
    assert "TASKS (top 5)" not in txt
    assert "GOAL:" in txt
    assert "POTCILJEVI" in txt
    assert "Name:" in txt


def test_ceo_advisor_fact_sensitive_empty_snapshot_is_grounded(monkeypatch):
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    # Even if LLM is configured, we must not assert business state without snapshot.
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    agent_input = DummyAgentInput(
        message="Da li smo blokirani?",
        snapshot={},
        metadata={"snapshot_source": "test"},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={}))
    txt = (out.text or "").lower()

    assert out.read_only is True
    assert "blokir" not in txt
    assert "refresh" in txt
    assert isinstance(out.trace, dict)
    assert isinstance(out.trace.get("grounding_gate"), dict)
