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


_CEO_INTRO_TEMPLATE = (
    "Ja sam CEO Advisor u ovom workspace-u. Pomažem ti da razmišljaš, planiraš i izvršiš stvari na siguran način.\n\n"
    "Kako radim:\n"
    "- READ-only po defaultu: mogu analizirati, sažeti i predložiti naredne korake.\n"
    "- Akcije su approval-gated: kad želiš da nešto mijenjam (npr. Notion/taskovi/DB), vratim prijedlog koji ti odobriš.\n"
    "- Ako izvori znanja (KB/snapshot) nisu dostupni, to ću reći i ostajem determinističan/offline-safe.\n\n"
    "Kako da pitaš:\n"
    "- Za plan: reci cilj + rok + ograničenja.\n"
    "- Za izvršenje: eksplicitno napiši šta da kreiram/izmijenim i pripremiću approval-gated prijedlog."
)


async def _stub_create_ceo_advisor_agent(*_args, **_kwargs) -> AgentOutput:
    return AgentOutput(
        text=_CEO_INTRO_TEMPLATE,
        proposed_commands=[],
        agent_id="ceo_advisor",
        read_only=True,
        trace={"exit_reason": "stub.ceo_intro_template"},
    )


def test_plan_review_must_not_show_intro_template(monkeypatch):
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
        "message": (
            "Procitaj ovaj plan i reci mi sta mislis: "
            "Cilj: rast prihoda u 90 dana. Kanali: SEO + outbound. Budzet: ogranicen. Rok: 3 mjeseca."
        ),
        "session_id": "session_ceo_intro_leak_1",
        "identity_pack": {"user_id": "test"},
    }

    r = client.post("/api/chat", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body.get("read_only") is True
    assert body.get("proposed_commands") == []

    txt = str(body.get("text") or "")
    assert "Ja sam CEO Advisor u ovom workspace-u" not in txt
    assert "Kako radim:" not in txt
    assert "Kako da pitaš:" not in txt

    # Must provide actual feedback, not generic boilerplate.
    assert "Snage" in txt
    assert "Poboljšanja" in txt
    assert "KPI" in txt

    md = body.get("metadata")
    assert isinstance(md, dict)
    dbg = md.get("debug")
    assert isinstance(dbg, dict)
    assert dbg.get("internal_system_text") == _CEO_INTRO_TEMPLATE


def test_explicit_meta_question_allows_intro_template(monkeypatch):
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
        "message": "Ko si ti i kako radiš u ovom workspace-u?",
        "session_id": "session_ceo_intro_allowed_1",
        "identity_pack": {"user_id": "test"},
    }

    r = client.post("/api/chat", json=payload)
    assert r.status_code == 200, r.text
    body = r.json()

    assert body.get("read_only") is True
    assert body.get("proposed_commands") == []

    txt = str(body.get("text") or "")
    assert "Ja sam CEO Advisor u ovom workspace-u" in txt
    assert "Kako radim:" in txt
    assert "Kako da pitaš:" in txt

    # Allowed meta answers must not be sanitized into metadata.
    assert "metadata" not in body


def test_anti_sticky_intro_template(monkeypatch):
    import routers.chat_router as chat_router

    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        _stub_create_ceo_advisor_agent,
        raising=True,
    )

    app = _load_app()
    client = TestClient(app)

    session_id = "session_ceo_intro_sticky_1"

    r1 = client.post(
        "/api/chat",
        json={
            "message": "Procitaj ovaj plan i reci mi sta mislis: Plan je fokus na SEO i outbound.",
            "session_id": session_id,
            "identity_pack": {"user_id": "test"},
        },
    )
    assert r1.status_code == 200, r1.text
    t1 = str(r1.json().get("text") or "")
    assert "Ja sam CEO Advisor u ovom workspace-u" not in t1

    r2 = client.post(
        "/api/chat",
        json={
            "message": "Ok, a sad reci mi 3 slabosti u planu",
            "session_id": session_id,
            "identity_pack": {"user_id": "test"},
        },
    )
    assert r2.status_code == 200, r2.text
    body2 = r2.json()

    assert body2.get("read_only") is True
    assert body2.get("proposed_commands") == []

    t2 = str(body2.get("text") or "")
    assert "Ja sam CEO Advisor u ovom workspace-u" not in t2
    assert "Kako radim:" not in t2
    assert "Kako da pitaš:" not in t2

    # Must provide analysis for weaknesses.
    assert "slabosti" in t2.lower() or "moguce" in t2.lower()
    assert "1)" in t2
    assert "2)" in t2
    assert "3)" in t2
