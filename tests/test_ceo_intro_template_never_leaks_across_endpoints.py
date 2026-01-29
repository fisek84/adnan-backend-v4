from __future__ import annotations

import json
from typing import Any

import pytest
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


def _assert_no_intro_template(txt: str) -> None:
    assert "Ja sam CEO Advisor u ovom workspace-u" not in txt
    assert "Kako radim:" not in txt
    assert "Kako da pitaš:" not in txt


def _assert_intro_template_present(txt: str) -> None:
    assert "Ja sam CEO Advisor u ovom workspace-u" in txt
    assert "Kako radim:" in txt
    assert "Kako da pitaš:" in txt


def _extract_text_from_stream_payload(raw: str) -> str:
    # Best-effort reconstruction for simple SSE/JSON-lines streams.
    out: list[str] = []
    for line in (raw or "").splitlines():
        l = line.strip()
        if not l:
            continue
        if l.startswith("data:"):
            payload = l[len("data:") :].strip()
            if payload in {"[DONE]", "done"}:
                continue
            try:
                obj = json.loads(payload)
            except Exception:
                out.append(payload)
                continue
            if isinstance(obj, dict):
                for k in ("text", "delta", "content"):
                    v = obj.get(k)
                    if isinstance(v, str) and v:
                        out.append(v)
            continue

        # Non-SSE: attempt JSON parse per line.
        try:
            obj = json.loads(l)
        except Exception:
            continue
        if isinstance(obj, dict):
            v = obj.get("text")
            if isinstance(v, str) and v:
                out.append(v)
    return "".join(out).strip()


def test_api_chat_two_turn_plan_repro_no_template(monkeypatch: pytest.MonkeyPatch) -> None:
    import routers.chat_router as chat_router

    calls: list[str] = []

    async def _stub_create_ceo_advisor_agent(*_args: Any, **_kwargs: Any) -> AgentOutput:
        calls.append("call")
        if len(calls) == 1:
            return AgentOutput(
                text="Nemam u KB/Memory/Snapshot nikakav plan, ali mogu analizirati ako ga pošalješ.",
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace={"exit_reason": "stub.turn1"},
            )
        return AgentOutput(
            text=_CEO_INTRO_TEMPLATE,
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={"exit_reason": "stub.turn2.intro_template"},
        )

    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        _stub_create_ceo_advisor_agent,
        raising=True,
    )

    app = _load_app()
    client = TestClient(app)

    session_id = "session_intro_repro_api_chat"

    r1 = client.post(
        "/api/chat",
        json={
            "message": "Mozes li analizirati plan za mene ?",
            "session_id": session_id,
            "identity_pack": {"user_id": "test"},
        },
    )
    assert r1.status_code == 200, r1.text

    r2 = client.post(
        "/api/chat",
        json={
            "message": "Evo ti plan koji treba da analiziras: Cilj: rast prihoda u 90 dana. Kanali: SEO+outbound.",
            "session_id": session_id,
            "identity_pack": {"user_id": "test"},
        },
    )
    assert r2.status_code == 200, r2.text

    body2 = r2.json()
    assert body2.get("read_only") is True
    assert body2.get("proposed_commands") == []

    txt2 = str(body2.get("text") or "")
    _assert_no_intro_template(txt2)

    # Must provide actual feedback (deterministic safe fallback).
    assert "Snage" in txt2
    assert "Poboljšanja" in txt2


def test_chat_alias_two_turn_plan_repro_no_template(monkeypatch: pytest.MonkeyPatch) -> None:
    # /chat alias is registered without /api prefix; sanitizer must still apply.
    import routers.chat_router as chat_router

    calls: list[str] = []

    async def _stub_create_ceo_advisor_agent(*_args: Any, **_kwargs: Any) -> AgentOutput:
        calls.append("call")
        if len(calls) == 1:
            return AgentOutput(
                text="OK — pošalji plan i analiziraću.",
                proposed_commands=[],
                agent_id="ceo_advisor",
                read_only=True,
                trace={"exit_reason": "stub.turn1"},
            )
        return AgentOutput(
            text=_CEO_INTRO_TEMPLATE,
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={"exit_reason": "stub.turn2.intro_template"},
        )

    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        _stub_create_ceo_advisor_agent,
        raising=True,
    )

    app = _load_app()
    client = TestClient(app)

    session_id = "session_intro_repro_chat_alias"

    r1 = client.post(
        "/chat",
        json={
            "message": "Mozes li analizirati plan za mene ?",
            "session_id": session_id,
            "identity_pack": {"user_id": "test"},
        },
    )
    assert r1.status_code == 200, r1.text

    r2 = client.post(
        "/chat",
        json={
            "message": "Evo ti plan koji treba da analiziras: Cilj: rast prihoda.",
            "session_id": session_id,
            "identity_pack": {"user_id": "test"},
        },
    )
    assert r2.status_code == 200, r2.text

    body2 = r2.json()
    txt2 = str(body2.get("text") or "")
    _assert_no_intro_template(txt2)


def test_streaming_endpoint_if_present(monkeypatch: pytest.MonkeyPatch) -> None:
    # If a streaming chat endpoint exists, it must also obey the no-template-leak invariant.
    import routers.chat_router as chat_router

    async def _stub_create_ceo_advisor_agent(*_args: Any, **_kwargs: Any) -> AgentOutput:
        return AgentOutput(
            text=_CEO_INTRO_TEMPLATE,
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={"exit_reason": "stub.stream.intro_template"},
        )

    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        _stub_create_ceo_advisor_agent,
        raising=True,
    )

    app = _load_app()
    paths = []
    for r in getattr(app, "routes", []):
        p = getattr(r, "path", None)
        if isinstance(p, str) and "stream" in p.lower() and "chat" in p.lower():
            paths.append(p)

    if not paths:
        pytest.skip("No streaming chat endpoint registered in this backend")

    client = TestClient(app)

    p0 = paths[0]
    resp = client.post(
        p0,
        json={
            "message": "Evo ti plan koji treba da analiziras: Cilj: rast prihoda.",
            "session_id": "session_stream_if_present",
        },
    )
    assert resp.status_code in {200, 404}, resp.text
    if resp.status_code == 404:
        pytest.skip("Streaming chat endpoint path exists in routes list but returns 404")

    raw = resp.text or ""
    reconstructed = _extract_text_from_stream_payload(raw) or raw
    _assert_no_intro_template(reconstructed)


def test_voice_endpoint_if_present_no_template_leak() -> None:
    # Voice endpoints should never emit the CEO intro template as user-visible text.
    app = _load_app()

    client = TestClient(app)

    # exec_text is a JSON endpoint (no audio upload required).
    resp = client.post(
        "/api/voice/exec_text",
        json={"text": "Evo ti plan koji treba da analiziras: Cilj: rast prihoda."},
    )

    if resp.status_code == 404:
        pytest.skip("Voice endpoint not present")

    assert resp.status_code == 200, resp.text
    raw = resp.text or ""
    assert "Ja sam CEO Advisor u ovom workspace-u" not in raw


def test_explicit_meta_question_allows_intro_template(monkeypatch: pytest.MonkeyPatch) -> None:
    import routers.chat_router as chat_router

    async def _stub_create_ceo_advisor_agent(*_args: Any, **_kwargs: Any) -> AgentOutput:
        return AgentOutput(
            text=_CEO_INTRO_TEMPLATE,
            proposed_commands=[],
            agent_id="ceo_advisor",
            read_only=True,
            trace={"exit_reason": "stub.meta.allowed"},
        )

    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        _stub_create_ceo_advisor_agent,
        raising=True,
    )

    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Ko si ti i kako radiš u ovom workspace-u?",
            "session_id": "session_intro_allowed_meta",
            "identity_pack": {"user_id": "test"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    assert body.get("read_only") is True
    assert body.get("proposed_commands") == []

    txt = str(body.get("text") or "")
    _assert_intro_template_present(txt)

    # Allowed meta answers must not be sanitized.
    assert "metadata" not in body
