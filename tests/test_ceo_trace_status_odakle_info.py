from __future__ import annotations

import asyncio
from dataclasses import dataclass


@dataclass
class DummyAgentInput:
    message: str
    snapshot: dict
    metadata: dict
    conversation_id: str | None = None


def test_trace_status_odakle_ti_info_and_izvor_do_not_fall_back_to_unknown_mode(
    monkeypatch,
):
    from services.ceo_advisor_agent import create_ceo_advisor_agent

    # Force the failure mode from the bug report: no LLM + allow_general=0 would normally lead to unknown_mode.
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")

    # Step 1: produce any deterministic output with trace present (exit_reason="ok" in many bypass paths).
    out1 = asyncio.run(
        create_ceo_advisor_agent(
            DummyAgentInput(
                message="procitaj ovo reci mi sta mislis i moze li se napraviti plan",
                snapshot={},
                metadata={"include_debug": True},
                conversation_id="trace-1",
            ),
            ctx={},
        )
    )
    assert out1.read_only is True

    # Step 2a: provenance question (odakle ti info)
    out2 = asyncio.run(
        create_ceo_advisor_agent(
            DummyAgentInput(
                message="Odakle ti info?",
                snapshot={},
                metadata={"include_debug": True},
                conversation_id="trace-1",
            ),
            ctx={
                "grounding_pack": {
                    "trace": {"used_sources": ["kb"], "not_used": []},
                }
            },
        )
    )
    txt2 = (out2.text or "").lower()
    assert "trenutno nemam to znanje" not in txt2
    assert ("korišteno:" in txt2) or ("used:" in txt2)

    # Step 2b: short variant (izvor?)
    out3 = asyncio.run(
        create_ceo_advisor_agent(
            DummyAgentInput(
                message="Izvor?",
                snapshot={},
                metadata={"include_debug": True},
                conversation_id="trace-1",
            ),
            ctx={
                "grounding_pack": {
                    "trace": {"used_sources": ["identity"], "not_used": []},
                }
            },
        )
    )
    txt3 = (out3.text or "").lower()
    assert "trenutno nemam to znanje" not in txt3
    assert ("korišteno:" in txt3) or ("used:" in txt3)
