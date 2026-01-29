import asyncio
from dataclasses import dataclass

import pytest


@dataclass
class DummyAgentInput:
    message: str
    snapshot: dict
    metadata: dict


@pytest.mark.parametrize(
    "user_text",
    [
        "dali ti imas pamcenje ?",
        "Kako pamtiš?",
    ],
)
def test_memory_meta_questions_bypass_unknown_mode_when_general_knowledge_disabled(
    monkeypatch,
    user_text: str,
):
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    # Match production hard mode: no general knowledge, offline-safe.
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    agent_input = DummyAgentInput(
        message=user_text,
        snapshot={},
        metadata={"ui_output_lang": "bs"},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={}))

    txt = (out.text or "").lower()
    assert out.read_only is True
    assert out.proposed_commands == []

    # Must not fall back to unknown-mode template.
    assert "trenutno nemam to znanje" not in txt
    assert "kuriranom kb-u" not in txt
    assert "snapshotu" not in txt

    # Must contain deterministic memory explanation.
    assert "kratkoro" in txt
    assert "dugoro" in txt

    tr = out.trace or {}
    assert tr.get("intent") == "assistant_memory"
