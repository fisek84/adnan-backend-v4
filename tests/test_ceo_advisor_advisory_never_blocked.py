import asyncio

from models.agent_contract import AgentInput
from services.ceo_advisor_agent import create_ceo_advisor_agent


def _run(coro):
    return asyncio.run(coro)


def _mk_executor(response_text: str):
    class _StubExecutor:
        async def ceo_command(self, *, text, context):
            return {"text": response_text, "proposed_commands": []}

    return _StubExecutor()


def test_advisory_never_blocked_a(monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda purpose=None: _mk_executor(
            "- Korak 1: Zapiši cilj u jednoj rečenici\n"
            "- Korak 2: Napravi plan u 3 bloka (fokus, izvedba, pregled)\n"
            "- Korak 3: Definiši najmanji sljedeći korak"
        ),
    )

    out = _run(
        create_ceo_advisor_agent(
            AgentInput(
                message="Kako da upravljam mislima i napravim bolji plan",
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
    assert "Ne mogu dati smislen odgovor" not in txt
    assert ("\n-" in txt) or ("\n1)" in txt) or ("\n2)" in txt)


def test_advisory_never_blocked_b(monkeypatch):
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda purpose=None: _mk_executor(
            "- Korak 1: Definiši odluku i kriterije\n"
            "- Korak 2: Ukloni 1 distrakciju i postavi tajmer 25 min\n"
            "- Korak 3: Pre-mortem + izbor"
        ),
    )

    out = _run(
        create_ceo_advisor_agent(
            AgentInput(
                message="Kako da poboljšam fokus i donesem bolju odluku",
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
    assert "Ne mogu dati smislen odgovor" not in txt
    assert ("\n-" in txt) or ("\n1)" in txt) or ("\n2)" in txt)


def test_fact_lookup_without_grounding_returns_canonical_no_answer(monkeypatch):
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
