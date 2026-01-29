import asyncio

from models.agent_contract import AgentInput
from services.ceo_advisor_agent import create_ceo_advisor_agent


BANNED_SUBSTRINGS = [
    "kb",
    "snapshot",
    "grounding",
    "mode",
    "guard",
    "kuriran",
    "notion snapshot",
    "policy",
    "offline",
]


def _run(coro):
    return asyncio.run(coro)


def _assert_no_banned_substrings(text: str) -> None:
    low = (text or "").lower()
    for s in BANNED_SUBSTRINGS:
        assert s not in low, f"banned substring leaked: {s}"


def test_canonical_no_answer_text_responses_missing_grounding(monkeypatch):
    # Match existing env toggles used by Responses grounding guard tests.
    monkeypatch.setenv("OPENAI_API_KEY", "test_key")
    monkeypatch.setenv("OPENAI_API_MODE", "responses")

    agent_input = AgentInput(
        message="Koji je glavni grad Francuske?",
        identity_pack={"payload": {"role": "ceo"}},
        snapshot={"payload": {"goals": [{"title": "G1"}], "tasks": []}},
        metadata={"session_id": "test_session_responses_guard", "ui_output_lang": "bs"},
    )

    out = _run(create_ceo_advisor_agent(agent_input, ctx={"grounding_pack": {}}))

    assert out.read_only is True
    assert out.proposed_commands == []
    assert "Ne mogu dati smislen odgovor" in (out.text or "")
    _assert_no_banned_substrings(out.text or "")


def test_canonical_no_answer_text_unknown_mode_fallback(monkeypatch):
    # Match existing unknown_mode fallback test setup (allow_general off).
    monkeypatch.setenv("OPENAI_API_MODE", "assistants")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")
    monkeypatch.setattr("services.ceo_advisor_agent._llm_is_configured", lambda: True)

    out = _run(
        create_ceo_advisor_agent(
            AgentInput(
                message="Koji je glavni grad Francuske?",
                snapshot={},
                metadata={"ui_output_lang": "bs"},
                preferred_agent_id="ceo_advisor",
            ),
            ctx={},
        )
    )

    assert out.read_only is True
    assert out.proposed_commands == []
    assert out.trace.get("intent") == "unknown_mode"
    assert "Ne mogu dati smislen odgovor" in (out.text or "")
    _assert_no_banned_substrings(out.text or "")
