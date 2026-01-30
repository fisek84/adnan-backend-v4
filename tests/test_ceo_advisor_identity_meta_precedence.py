import asyncio

from gateway.gateway_server import sanitize_user_visible_answer
from models.agent_contract import AgentInput
from services.ceo_advisor_agent import create_ceo_advisor_agent


def _run(coro):
    return asyncio.run(coro)


def test_identity_questions_never_sanitize_canonical_identity_answer(monkeypatch):
    # Deterministic: ensure we do not hit OpenAI.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr("services.ceo_advisor_agent._llm_is_configured", lambda: False)

    cases = [
        ("Koja je tvoja uloga u sistemu", "bs", "Ja sam CEO Advisor"),
        ("Ko si", "bs", "Ja sam CEO Advisor"),
        ("What is your role", "en", "CEO Advisor"),
    ]

    for prompt, ui_lang, must_contain in cases:
        out = _run(
            create_ceo_advisor_agent(
                AgentInput(
                    message=prompt,
                    identity_pack={"payload": {"role": "ceo"}},
                    snapshot={"payload": {"goals": [{"title": "G1"}], "tasks": []}},
                    metadata={"session_id": "test_identity_meta", "ui_output_lang": ui_lang},
                ),
                ctx={"grounding_pack": {}},
            )
        )

        assert out.read_only is True
        assert out.proposed_commands == []
        assert out.trace.get("intent") == "assistant_identity"

        text = out.text or ""
        assert must_contain in text

        # Critical: must not be sanitized into an advisory fallback by the gateway leak guard.
        # Include trace intent because real gateway responses include it.
        body = {
            "text": text,
            "metadata": {"debug": {}},
            "trace": dict(out.trace or {}),
            "agent_id": out.agent_id,
        }
        sanitized = sanitize_user_visible_answer(
            body_obj=body,
            prompt=prompt,
            session_id="test_identity_meta",
            conversation_id="test_identity_meta",
        )
        assert sanitized is None
