import asyncio
from dataclasses import dataclass


@dataclass
class DummyAgentInput:
    message: str
    snapshot: dict
    metadata: dict


def test_advisory_review_long_content_does_not_return_unknown_mode_or_contract_leaks(
    monkeypatch,
):
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    # Force deterministic/offline path (CI default).
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    long_body = "\n".join(
        [
            "NASLOV: Plan prodaje Q1",
            "\nSAZETAK:",
            "- Cilj: rast prihoda",
            "- Kanali: outbound + inbound",
            "\nDETALJI:",
        ]
        + [f"Stavka {i}: opis i pretpostavke." for i in range(1, 120)]
    )

    agent_input = DummyAgentInput(
        message="Procitaj ovaj plan i reci mi sta mislis:\n" + long_body,
        snapshot={},
        metadata={"snapshot_source": "test"},
    )

    out = asyncio.run(create_ceo_advisor_agent(agent_input, ctx={}))

    txt = out.text or ""
    assert out.read_only is True
    assert out.proposed_commands == []

    # Must not fall back to unknown-mode template.
    assert "trenutno nemam to znanje" not in txt.lower()

    # Must never leak internal contract/prompt strings.
    lowered = txt.lower()
    assert "required keys" not in lowered
    assert "proposed_commands" not in lowered
    assert "tačno dva ključa" not in lowered
    assert "tacno dva kljuca" not in lowered
