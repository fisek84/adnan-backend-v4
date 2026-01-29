from __future__ import annotations

import time

from fastapi import FastAPI
from fastapi.testclient import TestClient


def test_pending_proposal_cancel_on_negation_clears_state_and_continues_read_only(
    monkeypatch, tmp_path
):
    """Regression: negation must deterministically cancel pending proposal.

    Given:
    - pending proposal exists in ConversationStateStore.meta.pending_proposed_commands

    When:
    - user replies with a negation inside a longer sentence

    Then:
    - pending_proposed_commands is cleared
    - response is NOT pending_proposal_confirm_needed
    - continues normal READ-only advisory flow
    - proposed_commands == []
    """

    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_pending_cancel.json"),
    )

    # Patch the advisor so this test is deterministic and does not touch LLM/executor.
    from models.agent_contract import AgentOutput

    calls: list[str] = []

    async def _fake_ceo_advisor_agent(agent_input, ctx):  # noqa: ANN001
        calls.append(getattr(agent_input, "message", ""))
        return AgentOutput(
            text="OK (advisory)",
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={"intent": "advisory"},
        )

    monkeypatch.setattr(
        "routers.chat_router.create_ceo_advisor_agent", _fake_ceo_advisor_agent
    )

    # Seed pending proposal directly.
    from services.ceo_conversation_state_store import ConversationStateStore

    session_id = "session_pending_cancel_negation_1"

    ConversationStateStore.update_meta(
        conversation_id=session_id,
        updates={
            "pending_proposal": True,
            "pending_proposed_commands": [
                {
                    "command": "ceo.command.propose",
                    "intent": "ceo.command.propose",
                    "args": {"noop": True},
                    "dry_run": True,
                    "requires_approval": True,
                }
            ],
            "pending_proposal_created_at": float(time.time()),
            "pending_proposal_confirm_prompt_count": 0,
        },
    )

    app = FastAPI()
    from routers.chat_router import build_chat_router

    app.include_router(build_chat_router())
    client = TestClient(app)

    resp = client.post(
        "/chat",
        json={
            "message": "Ne zelim. Zanima me sta ti mislis",
            "session_id": session_id,
            "snapshot": {"payload": {"tasks": []}},
            "metadata": {"include_debug": True},
        },
    )

    assert resp.status_code == 200
    data = resp.json()

    # Must not enter pending-confirm loop.
    assert "Imam prijedlog na čekanju" not in (data.get("text") or "")
    tr = data.get("trace") or {}
    assert tr.get("intent") != "pending_proposal_confirm_needed"

    # Must continue normal READ-only advisory flow.
    assert data.get("read_only") is True
    assert (data.get("proposed_commands") or []) == []

    # Pending state MUST be cleared deterministically.
    meta = ConversationStateStore.get_meta(conversation_id=session_id)
    assert isinstance(meta, dict)
    assert meta.get("pending_proposed_commands") in (None, [])
    assert meta.get("pending_proposal") in (None, False)

    # Prove we continued to advisor (normal flow).
    assert calls == ["Ne zelim. Zanima me sta ti mislis"]
