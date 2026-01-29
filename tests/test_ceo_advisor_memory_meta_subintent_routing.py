import asyncio
from dataclasses import dataclass

import pytest


@dataclass
class DummyAgentInput:
    message: str
    snapshot: dict
    metadata: dict


@pytest.mark.parametrize(
    "user_text,expected_kind",
    [
        ("Da li imaš pamćenje?", "existence"),
        ("Kakvo pamćenje imaš, kratkoročno ili dugoročno?", "classification"),
        ("Kako radi tvoje pamćenje?", "process"),
    ],
)
def test_memory_meta_questions_route_to_expected_subintent(
    monkeypatch,
    tmp_path,
    user_text: str,
    expected_kind: str,
):
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "_ceo_conversation_state_test.json"),
    )

    agent_input = DummyAgentInput(
        message=user_text,
        snapshot={},
        metadata={"ui_output_lang": "bs"},
    )

    out = asyncio.run(
        create_ceo_advisor_agent(
            agent_input, ctx={"conversation_id": f"cid-{expected_kind}"}
        )
    )

    assert out.read_only is True
    assert out.proposed_commands == []

    txt = (out.text or "").lower()
    assert "trenutno nemam to znanje" not in txt

    # Must keep the canonical explanation keywords.
    assert "kratkoro" in txt
    assert "dugoro" in txt

    tr = out.trace or {}
    assert tr.get("intent") == "assistant_memory"
    assert tr.get("memory_meta_kind") == expected_kind


def test_memory_meta_followup_inherits_context_via_conversation_state(
    monkeypatch, tmp_path
):
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "_ceo_conversation_state_test.json"),
    )

    cid = "cid-followup"

    first = DummyAgentInput(
        message="Da li imaš pamćenje?",
        snapshot={},
        metadata={"ui_output_lang": "bs"},
    )
    out1 = asyncio.run(create_ceo_advisor_agent(first, ctx={"conversation_id": cid}))
    assert (out1.trace or {}).get("intent") == "assistant_memory"

    second = DummyAgentInput(
        message="Koju koristiš?",
        snapshot={},
        metadata={"ui_output_lang": "bs"},
    )
    out2 = asyncio.run(create_ceo_advisor_agent(second, ctx={"conversation_id": cid}))

    assert out2.read_only is True
    assert out2.proposed_commands == []

    txt2 = (out2.text or "").lower()
    assert "trenutno nemam to znanje" not in txt2
    assert "kratkoro" in txt2
    assert "dugoro" in txt2

    tr2 = out2.trace or {}
    assert tr2.get("intent") == "assistant_memory"
    assert tr2.get("memory_meta_kind") == "classification"


def test_memory_meta_followup_does_not_hijack_without_prior_memory_context(
    monkeypatch,
    tmp_path,
):
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "_ceo_conversation_state_test.json"),
    )

    agent_input = DummyAgentInput(
        message="Koju koristiš?",
        snapshot={},
        metadata={"ui_output_lang": "bs"},
    )

    out = asyncio.run(
        create_ceo_advisor_agent(agent_input, ctx={"conversation_id": "cid-no-prior"})
    )

    tr = out.trace or {}
    assert tr.get("intent") != "assistant_memory"
