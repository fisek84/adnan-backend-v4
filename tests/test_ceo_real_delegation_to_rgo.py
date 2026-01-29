from __future__ import annotations

import json

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_deliverable_proposal_then_confirm_executes_rgo_no_notion(
    monkeypatch, tmp_path
):
    """Deliverable delegation is proposal-only in /api/chat.

    Requirements:
    - No LLM/executor usage (mock)
    - Confirm step replays the same proposed_commands (no RGO call)
    - deliverable flow emits no Notion ops prompts/toggles
    - tasks=[] must not hijack into weekly/kickoff
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )
    monkeypatch.setenv("DEBUG_TRACE", "1")

    # Grounding pack can be missing/disabled; deliverable proposal/confirm must still work.
    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    calls: list[dict] = []

    async def _fake_growth_agent(agent_in, ctx):  # noqa: ANN001
        calls.append({"message": agent_in.message, "ctx": ctx})
        from models.agent_contract import AgentOutput

        payload = {
            "agent": "revenue_growth_operator",
            "task_id": "t_test",
            "objective": agent_in.message,
            "context_ref": {
                "lead_id": None,
                "account_id": None,
                "meeting_id": None,
                "campaign_id": None,
            },
            "work_done": [
                {
                    "type": "email_draft",
                    "title": "Email 1",
                    "content": "Email 1: Hello...",
                    "meta": {},
                },
                {
                    "type": "email_draft",
                    "title": "Email 2",
                    "content": "Email 2: Hi...",
                    "meta": {},
                },
            ],
            "next_steps": [],
            "recommendations_to_ceo": [],
            "requests_from_ceo": [],
            "notion_ops_proposal": [],
        }

        return AgentOutput(
            text=json.dumps(payload, ensure_ascii=False),
            proposed_commands=[],
            agent_id="revenue_growth_operator",
            read_only=True,
            trace={"stub": True},
        )

    monkeypatch.setattr(
        "services.revenue_growth_operator_agent.revenue_growth_operator_agent",
        _fake_growth_agent,
    )

    app = _load_app()
    client = TestClient(app)

    session_id = "session_real_delegation_1"

    snap = {"payload": {"tasks": []}}

    # Step 1: deliverable request -> proposal (no real execution yet)
    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pripremi 3 follow-up poruke + 2 emaila za leadove.",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp1.status_code == 200
    data1 = resp1.json()

    # ACK discipline: must acknowledge before asking to delegate.
    txt1 = (data1.get("text") or "").lower()
    assert "razumijem" in txt1 or "got it" in txt1

    assert data1.get("agent_id") == "ceo_advisor"
    pcs1 = data1.get("proposed_commands") or []
    assert isinstance(pcs1, list) and len(pcs1) >= 1
    assert "notion" not in (data1.get("text") or "").lower()
    assert calls == [], "RGO must not be called before confirmation"

    # Step 2: short confirm -> replay same proposal (no execution)
    resp2 = client.post(
        "/api/chat",
        json={
            "message": "Da",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()

    assert calls == [], "RGO must not be called on confirmation"

    txt2 = data2.get("text") or ""
    assert "json" not in txt2.lower(), "Must not enter JSON-mode prompt"

    pcs2 = data2.get("proposed_commands") or []
    assert pcs2 == pcs1

    tr2 = data2.get("trace") or {}
    assert tr2.get("intent") == "approve_last_proposal_replay"


def test_weekly_explicit_does_not_call_rgo(monkeypatch, tmp_path):
    """Weekly explicit routes to CEO weekly flow, not RGO."""

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state.json")
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    calls: list[int] = []

    async def _fake_growth_agent(_agent_in, _ctx):  # noqa: ANN001
        calls.append(1)
        from models.agent_contract import AgentOutput

        return AgentOutput(
            text=json.dumps({"agent": "revenue_growth_operator"}, ensure_ascii=False),
            proposed_commands=[],
            agent_id="revenue_growth_operator",
            read_only=True,
            trace={"stub": True},
        )

    monkeypatch.setattr(
        "services.revenue_growth_operator_agent.revenue_growth_operator_agent",
        _fake_growth_agent,
    )

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    app = _load_app()
    client = TestClient(app)

    resp = client.post(
        "/api/chat",
        json={
            "message": "Daj mi sedmične prioritete i sedmični plan.",
            "session_id": "session_weekly_no_rgo_1",
            "snapshot": {
                "payload": {
                    "tasks": [],
                    "projects": [{"id": "p1", "title": "P"}],
                    "goals": [{"id": "g1", "title": "G"}],
                }
            },
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("agent_id") == "ceo_advisor"
    assert calls == []

    txt = data.get("text") or ""
    assert "TASKS snapshot" in txt


def test_pasted_deliverable_keywords_without_request_verbs_does_not_propose_delegation(
    monkeypatch, tmp_path
):
    """Regression: pasted content mentioning poruka/email/sekvence must not trigger delegation.

    Only explicit request verbs (napiši/pripremi/sastavi/kreiraj/...) should produce deliverable proposals.
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_pasted_deliverables.json"),
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    app = _load_app()
    client = TestClient(app)

    msg = (
        "DRAFT (copy/paste):\n\n"
        "Email sekvence:\n- Email 1: ...\n- Email 2: ...\n\n"
        "Poruke / follow-up:\n- Poruka 1: ...\n- Poruka 2: ...\n"
    )

    resp = client.post(
        "/api/chat",
        json={
            "message": msg,
            "session_id": "session_pasted_deliverables_no_verbs_1",
            "snapshot": {"payload": {"tasks": []}},
            "metadata": {"include_debug": True},
        },
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data.get("agent_id") == "ceo_advisor"
    assert data.get("read_only") is True
    assert (data.get("proposed_commands") or []) == []

    tr = data.get("trace") or {}
    assert tr.get("intent") != "deliverable_proposal"


def test_moze_phrase_is_not_treated_as_deliverable_confirm(monkeypatch, tmp_path):
    """Regression: words like 'moze/može' must not trigger deliverable confirmation.

    Otherwise any normal question ("da li mi agent moze...") would incorrectly execute
    the pending deliverable delegation.
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state_moze.json")
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    calls: list[int] = []

    async def _fake_growth_agent(_agent_in, _ctx):  # noqa: ANN001
        calls.append(1)
        from models.agent_contract import AgentOutput

        return AgentOutput(
            text="SHOULD_NOT_RUN",
            proposed_commands=[],
            agent_id="revenue_growth_operator",
            read_only=True,
            trace={"stub": True},
        )

    monkeypatch.setattr(
        "services.revenue_growth_operator_agent.revenue_growth_operator_agent",
        _fake_growth_agent,
    )

    app = _load_app()
    client = TestClient(app)

    session_id = "session_moze_not_confirm_1"
    snap = {"payload": {"tasks": []}}

    # Step 1: deliverable request -> proposal (no execution)
    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pripremi 2 follow-up poruke + 1 email.",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp1.status_code == 200
    assert calls == []

    # Step 2: contains "moze" but is NOT a confirmation -> must not execute RGO
    resp2 = client.post(
        "/api/chat",
        json={
            "message": "Da li mi agent moze pomoci da napravim plan?",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp2.status_code == 200
    assert calls == []


def test_pending_proposal_decline_clears_replay(monkeypatch, tmp_path):
    """Regression: user can say NO to cancel a pending proposal.

    Without this, users get stuck in a replay loop where a later short "Da"
    keeps replaying an unwanted pending proposal.
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state_decline.json")
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    app = _load_app()
    client = TestClient(app)

    session_id = "session_decline_clears_pending_1"
    snap = {"payload": {"tasks": []}}

    # Step 1: deliverable request -> proposal
    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pripremi 2 follow-up poruke + 1 email.",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp1.status_code == 200
    pcs1 = resp1.json().get("proposed_commands") or []
    assert isinstance(pcs1, list) and len(pcs1) >= 1

    # Step 2: user declines -> clear pending proposal
    resp2 = client.post(
        "/api/chat",
        json={
            "message": "Ne",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    tr2 = data2.get("trace") or {}
    assert tr2.get("intent") != "approve_last_proposal_replay"

    # Step 3: short yes should NOT replay the old proposal anymore
    resp3 = client.post(
        "/api/chat",
        json={
            "message": "Da",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp3.status_code == 200
    data3 = resp3.json()
    pcs3 = data3.get("proposed_commands") or []
    assert pcs3 != pcs1


def test_pending_new_request_cancels_and_routes(monkeypatch, tmp_path):
    """Pending + NEW_REQUEST => cancel pending + continue with new intent (no replay)."""

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state_newreq.json")
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    app = _load_app()
    client = TestClient(app)

    session_id = "session_pending_new_request_1"
    snap = {"payload": {"tasks": []}}

    # Step 1: deliverable request -> produces a pending proposal
    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pripremi 3 follow-up poruke + 2 emaila.",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp1.status_code == 200
    pcs1 = resp1.json().get("proposed_commands") or []
    assert isinstance(pcs1, list) and pcs1

    # Step 2: NEW_REQUEST while pending -> must cancel pending and not replay
    resp2 = client.post(
        "/api/chat",
        json={
            "message": "Umjesto delegacije, napravi plan i prioritete.",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    tr2 = data2.get("trace") or {}
    assert tr2.get("intent") != "approve_last_proposal_replay"
    txt2 = (data2.get("text") or "").lower()
    assert "zeli" not in txt2 or "delegir" not in txt2
    assert "delegiram? potvrdi" not in txt2


def test_pending_unknown_twice_prompts_once_then_auto_cancels(monkeypatch, tmp_path):
    """Pending + UNKNOWN => ask confirm once; second UNKNOWN auto-cancels and continues."""

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH", str(tmp_path / "ceo_conv_state_unknown2.json")
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    app = _load_app()
    client = TestClient(app)

    session_id = "session_pending_unknown_twice_1"
    snap = {"payload": {"tasks": []}}

    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pripremi 2 follow-up poruke + 1 email.",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp1.status_code == 200
    pcs1 = resp1.json().get("proposed_commands") or []
    assert isinstance(pcs1, list) and pcs1

    # First UNKNOWN -> router asks for confirm (no replay)
    resp2 = client.post(
        "/api/chat",
        json={
            "message": "hmm",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    tr2 = data2.get("trace") or {}
    assert tr2.get("intent") == "pending_proposal_confirm_needed"

    # Second UNKNOWN -> auto-cancel; must not replay
    resp3 = client.post(
        "/api/chat",
        json={
            "message": "hmm",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp3.status_code == 200
    data3 = resp3.json()
    tr3 = data3.get("trace") or {}
    assert tr3.get("intent") != "approve_last_proposal_replay"
    pcs3 = data3.get("proposed_commands") or []
    assert pcs3 != pcs1


def test_pending_decline_then_advisory_cancels_pending_and_continues(
    monkeypatch, tmp_path
):
    """Regression: negation + advisory must cancel pending proposal and continue.

    Repro: when a pending proposal exists and user replies with a decline + advisory intent
    (e.g., "Ne zelim. Zanima me sta ti mislis"), router must:
    - cancel pending_proposed_commands
    - avoid pending_proposal_confirm_needed loop
    - continue normal READ-only advisory routing
    - not fall into unknown-mode
    """

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_pending_cancel.json"),
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    app = _load_app()
    client = TestClient(app)

    session_id = "session_pending_cancel_advisory_1"
    snap = {"payload": {"tasks": []}}

    # Step 1: create a pending proposal
    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pripremi 2 follow-up poruke + 1 email.",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp1.status_code == 200
    data1 = resp1.json()
    pcs1 = data1.get("proposed_commands") or []
    assert isinstance(pcs1, list) and pcs1

    # Step 2: decline + advisory
    resp2 = client.post(
        "/api/chat",
        json={
            "message": "Ne zelim. Zanima me sta ti mislis.",
            "session_id": session_id,
            "snapshot": snap,
            "metadata": {"include_debug": True},
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()

    tr2 = data2.get("trace") or {}
    assert tr2.get("intent") != "pending_proposal_confirm_needed"
    assert tr2.get("intent") != "approve_last_proposal_replay"

    # Must not keep the user in pending jail.
    txt2 = (data2.get("text") or "").lower()
    assert "imam prijedlog na cekanju" not in txt2
    assert "trenutno nemam" not in txt2
    assert "ne delegiram deliverable" not in txt2

    assert data2.get("read_only") is True
    assert (data2.get("proposed_commands") or []) == []

    # Pending must be cleared in ConversationStateStore meta.
    from services.ceo_conversation_state_store import ConversationStateStore

    meta = ConversationStateStore.get_meta(conversation_id=session_id)
    assert isinstance(meta, dict)
    assert meta.get("pending_proposed_commands") in (None, [])
    assert meta.get("pending_proposal") in (None, False)


def test_ssot_missing_no_hallucinated_goals_tasks(monkeypatch, tmp_path):
    """Regression: when SSOT snapshot is missing/unavailable, the agent must not print fabricated GOALS/TASKS tables."""

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_ssot_missing.json"),
    )

    # Grounding pack must be present for responses-mode LLM path.
    from services.grounding_pack_service import GroundingPackService

    def _fake_gp_build(**_kwargs):  # noqa: ANN001
        return {
            "enabled": True,
            "identity_pack": {"payload": {"org": "test"}},
            "kb_retrieved": {"entries": [], "used_entry_ids": []},
            "notion_snapshot": {},
            "memory_snapshot": {"payload": {}},
        }

    monkeypatch.setattr(GroundingPackService, "build", _fake_gp_build)

    class _FakeExecutor:
        async def ceo_command(self, text, context):  # noqa: ANN001
            return {
                "text": "GOALS (top 3)\n1) Fake\n\nTASKS (top 5)\n1) Fake",
                "proposed_commands": [],
            }

    monkeypatch.setattr(
        "services.agent_router.executor_factory.get_executor",
        lambda **_kwargs: _FakeExecutor(),
    )

    app = _load_app()
    client = TestClient(app)

    # Explicitly mark snapshot unavailable.
    snap = {"payload": {"available": False, "error": "missing"}, "ready": False}

    resp = client.post(
        "/api/chat",
        json={
            "message": "Daj mi pregled ciljeva i taskova.",
            "session_id": "session_ssot_missing_1",
            "snapshot": snap,
        },
    )
    assert resp.status_code == 200
    txt = resp.json().get("text") or ""
    assert "Nemam SSOT snapshot" in txt or "don't have an SSOT snapshot" in txt
    assert "GOALS" not in txt
    assert "TASKS" not in txt


def test_decline_deliverables_new_request_does_not_loop(monkeypatch, tmp_path):
    """Regression: "ne trebaju deliverable-i" should not trigger repeated "Želiš da delegiram?" loops."""

    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_decline_new_req.json"),
    )

    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setattr(
        GroundingPackService, "build", lambda **kwargs: {"enabled": False}
    )

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    app = _load_app()
    client = TestClient(app)

    session_id = "session_decline_new_request_1"
    snap = {"payload": {"tasks": []}}

    # Step 1: deliverable request -> proposal
    resp1 = client.post(
        "/api/chat",
        json={
            "message": "Pripremi 3 follow-up poruke + 2 emaila.",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp1.status_code == 200
    txt1 = resp1.json().get("text") or ""
    assert "delegiram" in txt1.lower()

    # Step 2: decline + new request (plan) -> must not keep asking for delegation confirmation
    resp2 = client.post(
        "/api/chat",
        json={
            "message": "Ne trebaju deliverable-i. Treba mi plan i prioriteti.",
            "session_id": session_id,
            "snapshot": snap,
        },
    )
    assert resp2.status_code == 200
    data2 = resp2.json()
    txt2 = (data2.get("text") or "").lower()
    # Must not keep asking for delegation confirmation.
    assert "delegiram? potvrdi" not in txt2
    assert "to proceed, confirm" not in txt2

    # Must not emit delegation proposals on this turn.
    pcs2 = data2.get("proposed_commands")
    assert pcs2 in ([], None)
