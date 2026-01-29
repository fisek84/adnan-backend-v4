import asyncio
from dataclasses import dataclass


@dataclass
class DummyAgentInput:
    message: str
    snapshot: dict
    metadata: dict


def test_identity_questions_bypass_unknown_mode_when_general_knowledge_disabled(
    monkeypatch,
):
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    # Force offline/deterministic environment.
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    agent_input = DummyAgentInput(
        message="Koja je tvoja uloga?",
        snapshot={},
        metadata={"ui_output_lang": "bs"},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={}))

    txt = (out.text or "").lower()
    assert out.read_only is True
    assert out.proposed_commands == []

    # Must not fall back to unknown-mode template.
    assert "trenutno nemam to znanje" not in txt

    tr = out.trace or {}
    assert tr.get("intent") == "assistant_identity"
