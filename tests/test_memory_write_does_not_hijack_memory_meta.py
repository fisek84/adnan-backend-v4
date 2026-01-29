import asyncio

from models.agent_contract import AgentInput
from models.canon import PROPOSAL_WRAPPER_INTENT
from services.ceo_advisor_agent import create_ceo_advisor_agent


def test_memory_meta_question_never_proposes_write(monkeypatch):
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    out = asyncio.run(
        create_ceo_advisor_agent(
            AgentInput(
                message="kakvu memoriju koristiš?",
                snapshot={},
                metadata={"ui_output_lang": "bs"},
                preferred_agent_id="ceo_advisor",
            ),
            ctx={},
        )
    )

    assert out.read_only is True
    assert out.proposed_commands == []

    txt = out.text or ""
    low = txt.lower()

    assert "kratkoro" in low
    assert "dugoro" in low

    assert "zapamti ovo" not in low
    assert "proširi znanje" not in low
    assert "prosiri znanje" not in low
    assert "snim" not in low


def test_memory_write_request_still_creates_approval_gated_proposal(monkeypatch):
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    out = asyncio.run(
        create_ceo_advisor_agent(
            AgentInput(
                message="Zapamti ovo: Klijent A želi demo u utorak.",
                snapshot={},
                metadata={"ui_output_lang": "bs"},
                preferred_agent_id="ceo_advisor",
            ),
            ctx={},
        )
    )

    assert out.read_only is True
    assert out.proposed_commands

    pc = out.proposed_commands[0]
    assert pc.command == PROPOSAL_WRAPPER_INTENT
    assert pc.requires_approval is True
    assert pc.intent == "memory_write"

    args = pc.args or {}
    assert args.get("schema_version") == "memory_write.v1"
