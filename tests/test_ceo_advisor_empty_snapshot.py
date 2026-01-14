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
    assert "NEMA DOVOLJNO PODATAKA" not in (out.text or "").upper()
    assert ("?" in (out.text or "")) or ("KRENIMO" in (out.text or "").upper())
