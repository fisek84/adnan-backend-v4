import asyncio

import pytest

from models.agent_contract import AgentInput
from services.ceo_advisor_agent import create_ceo_advisor_agent


def _run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "message",
    [
        "Kako da upravljam mislima i napravi bolji plan",
        "Kako da poboljšam fokus i donesem bolju odluku",
    ],
)
def test_advisory_questions_bypass_responses_missing_grounding_no_answer(
    monkeypatch, message
):
    # Force Responses-mode path and missing grounding.
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")

    class _StubExecutor:
        async def ceo_command(self, text, context):
            return {
                "text": "- Korak 1: Definiši cilj\n- Korak 2: Izaberi 3 prioriteta\n- Korak 3: Napravi prvi mali potez",
                "proposed_commands": [],
            }

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda purpose=None: _StubExecutor(),
    )

    out = _run(
        create_ceo_advisor_agent(
            AgentInput(
                message=message,
                snapshot={},
                metadata={"ui_output_lang": "bs"},
                preferred_agent_id="ceo_advisor",
            ),
            ctx={"grounding_pack": {}},
        )
    )

    assert out.read_only is True
    assert out.proposed_commands == []

    txt = out.text or ""
    low = txt.lower()

    # Must not return canonical no-answer fallback.
    assert "ne mogu dati smislen odgovor" not in low

    # Must contain actionable structure (sections/bullets).
    assert ("\n-" in txt) or ("\n1)" in txt) or ("\n2)" in txt)


def test_fact_lookup_without_grounding_still_returns_canonical_no_answer(monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")

    def _boom(*args, **kwargs):
        raise AssertionError(
            "executor must not be called for fact lookup without grounding"
        )

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    out = _run(
        create_ceo_advisor_agent(
            AgentInput(
                message="Koji je glavni grad Francuske?",
                snapshot={},
                metadata={"ui_output_lang": "bs"},
                preferred_agent_id="ceo_advisor",
            ),
            ctx={"grounding_pack": {}},
        )
    )

    assert out.read_only is True
    assert out.proposed_commands == []
    assert "Ne mogu dati smislen odgovor" in (out.text or "")
