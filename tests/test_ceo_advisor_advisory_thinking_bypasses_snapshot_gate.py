import asyncio
from dataclasses import dataclass


@dataclass
class DummyAgentInput:
    message: str
    snapshot: dict
    metadata: dict


def test_ceo_advisor_advisory_thinking_prompt_does_not_require_snapshot(monkeypatch):
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    # Simulate a normal environment (LLM may be configured), but this test must not
    # depend on external network calls.
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    agent_input = DummyAgentInput(
        message=(
            "Pročitaj ovo i reci mi šta misliš o status projekta; "
            "može li se napraviti plan za sljedeću sedmicu?\n\n"
            "Kontekst: projekat Phoenix; imamo 2 developera, rok je za 10 dana, klijent traži promjene opsega."
        ),
        snapshot={},
        metadata={"snapshot_source": "test"},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={}))
    txt = (out.text or "")
    low = txt.lower()

    assert out.read_only is True

    # Must not demand snapshot/refresh/READ-context for advisory/thinking prompts.
    assert "ssot" not in low
    assert "snapshot" not in low
    assert "refresh" not in low
    assert "read kontek" not in low

    # Should still be helpful coaching output.
    assert ("plan" in low) or ("pitan" in low) or ("prioritet" in low)
