from __future__ import annotations

from fastapi.testclient import TestClient

from models.agent_contract import AgentOutput


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


_INTERNAL_MEMORY_BOILERPLATE = (
    "Vrste pamćenja koje koristim:\n"
    "- Kratkoročno: kontekst tekućeg razgovora (u okviru sesije).\n"
    "- Dugoročno (approval-gated): činjenice u Notion/KB samo kad ti eksplicitno odobriš.\n\n"
    "Ne pamtim ništa implicitno. WRITE ide propose → approve → execute."
)


async def _stub_create_ceo_advisor_agent(*_args, **_kwargs) -> AgentOutput:
    return AgentOutput(
        text=_INTERNAL_MEMORY_BOILERPLATE,
        proposed_commands=[],
        agent_id="ceo_advisor",
        read_only=True,
        trace={"exit_reason": "stub.internal_system_text"},
    )


def test_no_internal_snapshot_text_leaks_to_user_and_no_sticky_loop(monkeypatch):
    # Force the underlying agent to return the internal boilerplate, then assert
    # the gateway contract-enforcer strips it from user-visible `text`.
    import routers.chat_router as chat_router

    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        _stub_create_ceo_advisor_agent,
        raising=True,
    )

    app = _load_app()
    client = TestClient(app)

    session_id = "test-session-internal-text-leak"

    payload_a = {
        "message": "Dali imamo agente u sistemu i koje",
        "session_id": session_id,
        "identity_pack": {"user_id": "test"},
    }
    r1 = client.post("/api/chat", json=payload_a)
    assert r1.status_code == 200, r1.text
    body1 = r1.json()

    assert body1.get("read_only") is True
    assert body1.get("proposed_commands") == []

    t1 = str(body1.get("text") or "")
    assert "Vrste pamćenja koje koristim" not in t1
    assert "Kratkoročno" not in t1
    assert "Dugoročno" not in t1
    assert "propose → approve → execute" not in t1

    # Natural-ish agent/registry answer expected.
    assert ("Aktivni agenti" in t1) or ("agent_id" in t1)

    md1 = body1.get("metadata")
    assert isinstance(md1, dict)
    dbg1 = md1.get("debug")
    assert isinstance(dbg1, dict)
    assert dbg1.get("internal_system_text") == _INTERNAL_MEMORY_BOILERPLATE

    payload_b = {
        "message": "Daj mi kratke naredne korake za ovo.",
        "session_id": session_id,
        "identity_pack": {"user_id": "test"},
    }
    r2 = client.post("/api/chat", json=payload_b)
    assert r2.status_code == 200, r2.text
    body2 = r2.json()

    assert body2.get("read_only") is True
    assert body2.get("proposed_commands") == []

    t2 = str(body2.get("text") or "")
    assert t2
    assert t2 != t1
    assert "Vrste pamćenja koje koristim" not in t2
    assert "Kratkoročno" not in t2
    assert "Dugoročno" not in t2


def test_internal_memory_explanation_allowed_when_user_asks(monkeypatch):
    import routers.chat_router as chat_router

    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        _stub_create_ceo_advisor_agent,
        raising=True,
    )

    app = _load_app()
    client = TestClient(app)

    payload = {
        "message": "Kakvu memoriju koristiš?",
        "session_id": "test-session-allowed-memory",
        "identity_pack": {"user_id": "test"},
    }

    r = client.post("/api/chat", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body.get("read_only") is True
    assert body.get("proposed_commands") == []

    txt = str(body.get("text") or "")
    assert "Vrste pamćenja koje koristim" in txt

    # When explicitly asked, the contract-enforcer should NOT move it to debug.
    assert "metadata" not in body
