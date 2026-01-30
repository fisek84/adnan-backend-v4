import asyncio

import pytest

from models.agent_contract import AgentInput
from services.ceo_advisor_agent import create_ceo_advisor_agent


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "payload_heading",
    [
        "KO SI TI (POZICIJA)",
        "WHAT IS YOUR ROLE",
        "ABOUT ME",
        "HOW IT WORKS",
    ],
)
def test_payload_keywords_do_not_hijack_intent_when_directive_is_analysis(
    monkeypatch, payload_heading
):
    # Deterministic: ensure we do not hit OpenAI.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("services.ceo_advisor_agent._llm_is_configured", lambda: False)

    # User asks for analysis; pasted payload contains meta/identity-ish headings.
    msg = (
        "Analiziraj i reci mišljenje:\n\n"
        "Plan: fokus na SEO i outbound. Rok: 90 dana.\n\n"
        f"{payload_heading}\n"
        "- Ovo je samo naslov u dokumentu, nije pitanje asistentu.\n"
    )

    out = _run(
        create_ceo_advisor_agent(
            AgentInput(
                message=msg,
                identity_pack={"payload": {"role": "ceo"}},
                snapshot={"payload": {"goals": [{"title": "G1"}], "tasks": []}},
                metadata={"session_id": "test_identity_heading", "ui_output_lang": "bs"},
            ),
            ctx={"grounding_pack": {}},
        )
    )

    assert out.read_only is True
    assert out.proposed_commands == []

    tr = out.trace or {}
    assert tr.get("intent") != "assistant_identity"

    txt = str(out.text or "")
    assert "Ja sam CEO Advisor u ovom workspace-u" not in txt
    assert "Kako radim:" not in txt
    assert "Kako da pitaš:" not in txt


def test_payload_only_long_paste_that_starts_with_identity_like_heading_does_not_trigger_identity(
    monkeypatch,
):
    # Deterministic: ensure we do not hit OpenAI.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("services.ceo_advisor_agent._llm_is_configured", lambda: False)

    # No explicit directive; user pastes a long document (e.g., after being asked to send a plan).
    # Even if the first line looks like an identity heading, it must not flip intent.
    msg = (
        "KO SI TI (POZICIJA)\n"
        "Ovo je sekcija u dokumentu, nije pitanje asistentu.\n\n"
        "PLAN\n"
        "- Fokus: SEO + outbound\n"
        "- Rok: 90 dana\n"
        "- KPI: 50 SQL/m\n"
    )

    out = _run(
        create_ceo_advisor_agent(
            AgentInput(
                message=msg,
                identity_pack={"payload": {"role": "ceo"}},
                snapshot={"payload": {"goals": [{"title": "G1"}], "tasks": []}},
                metadata={"session_id": "test_payload_only_long_paste", "ui_output_lang": "bs"},
            ),
            ctx={"grounding_pack": {}, "conversation_state": "assistant: posalji plan"},
        )
    )

    tr = out.trace or {}
    assert tr.get("intent") != "assistant_identity"

    txt = str(out.text or "")
    assert "Ja sam CEO Advisor u ovom workspace-u" not in txt
    assert "Kako radim:" not in txt
    assert "Kako da pitaš:" not in txt
