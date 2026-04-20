from __future__ import annotations

import json
from typing import Any, Dict, Iterable, Optional

from fastapi.testclient import TestClient

from models.agent_contract import AgentOutput


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


_MEMORY_TEMPLATE = (
    "Vrste pamćenja koje koristim:\n"
    "- Kratkoročno: kontekst tekućeg razgovora (u okviru sesije).\n"
    "- Dugoročno (approval-gated): činjenice u Notion/KB samo kad ti eksplicitno odobriš.\n\n"
    "Ne pamtim ništa implicitno. WRITE ide propose → approve → execute."
)

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


def _mk_stub_agent_output(text: str) -> AgentOutput:
    return AgentOutput(
        text=text,
        proposed_commands=[],
        agent_id="ceo_advisor",
        read_only=True,
        trace={"exit_reason": "stub.response_sanitizer_matrix"},
    )


async def _stub_create_ceo_advisor_agent_with_text(
    text: str, *_args, **_kwargs
) -> AgentOutput:
    return _mk_stub_agent_output(text)


def _post_chat(
    client: TestClient,
    *,
    prompt: str,
    session_id: str,
) -> Dict[str, Any]:
    r = client.post(
        "/api/chat",
        json={
            "message": prompt,
            "session_id": session_id,
            "identity_pack": {"user_id": "test"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert isinstance(body, dict)
    return body


def _post_chat_stream_final(
    client: TestClient,
    *,
    prompt: str,
    session_id: str,
) -> Dict[str, Any]:
    r = client.post(
        "/api/chat/stream",
        json={
            "message": prompt,
            "session_id": session_id,
            "identity_pack": {"user_id": "test"},
        },
    )
    assert r.status_code == 200, r.text

    final_evt: Optional[Dict[str, Any]] = None
    for raw_line in r.iter_lines():
        if not raw_line:
            continue
        evt = json.loads(raw_line)
        if isinstance(evt, dict) and evt.get("type") == "assistant.final":
            final_evt = evt
            break
    assert isinstance(final_evt, dict), "missing assistant.final"
    data = final_evt.get("data")
    assert isinstance(data, dict), "assistant.final missing data"
    assert isinstance(data.get("response"), dict), "assistant.final missing response"
    return data


def _assert_trace_contract(
    trace: Dict[str, Any],
    *,
    triggered: bool,
    action: str,
    reason_code: str,
    marker_kind: str,
    allowlisted_this_turn: bool,
    redaction_applied: bool,
    replacement_applied: bool,
    minimal_damage: bool,
):
    tg = trace.get("turn_gate")
    assert isinstance(tg, dict), "trace.turn_gate missing"
    rs = tg.get("response_sanitizer")
    assert isinstance(rs, dict), "trace.response_sanitizer missing"
    assert rs.get("version") == 1
    assert rs.get("triggered") is triggered
    assert rs.get("action") == action
    assert rs.get("reason_code") == reason_code
    assert rs.get("marker_kind") == marker_kind
    assert rs.get("allowlisted_this_turn") is allowlisted_this_turn
    assert rs.get("redaction_applied") is redaction_applied
    assert rs.get("replacement_applied") is replacement_applied
    assert rs.get("minimal_damage") is minimal_damage


def _must_not_contain_any(text: str, needles: Iterable[str]) -> None:
    for n in needles:
        assert n not in text


def test_no_action_clean_passthrough_has_trace(monkeypatch):
    import routers.chat_router as chat_router

    clean = (
        "Evo 3 naredna koraka: 1) Definiši KPI 2) Postavi timeline 3) Dodijeli owner-a."
    )
    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        lambda *_a, **_k: _stub_create_ceo_advisor_agent_with_text(clean),
        raising=True,
    )

    client = TestClient(_load_app())
    body = _post_chat(
        client, prompt="Daj mi 3 naredna koraka za ovaj plan rasta.", session_id="rs_a1"
    )

    assert body.get("text") == clean
    tr = body.get("trace")
    assert isinstance(tr, dict)
    _assert_trace_contract(
        tr,
        triggered=False,
        action="NO_ACTION",
        reason_code="NO_TRIGGER",
        marker_kind="NONE",
        allowlisted_this_turn=False,
        redaction_applied=False,
        replacement_applied=False,
        minimal_damage=True,
    )


def test_allowlisted_memory_meta_question_no_action(monkeypatch):
    import routers.chat_router as chat_router

    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        lambda *_a, **_k: _stub_create_ceo_advisor_agent_with_text(_MEMORY_TEMPLATE),
        raising=True,
    )

    client = TestClient(_load_app())
    body = _post_chat(client, prompt="Kakvu memoriju koristiš?", session_id="rs_a2")

    assert "Vrste pamćenja" in str(body.get("text") or "")
    tr = body.get("trace")
    assert isinstance(tr, dict)
    _assert_trace_contract(
        tr,
        triggered=False,
        action="NO_ACTION",
        reason_code="ALLOWLIST_EXPLICIT_META_QUESTION",
        marker_kind="INTERNAL_MEMORY_TEMPLATE",
        allowlisted_this_turn=True,
        redaction_applied=False,
        replacement_applied=False,
        minimal_damage=True,
    )


def test_allowlisted_identity_howto_no_action(monkeypatch):
    import routers.chat_router as chat_router

    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        lambda *_a, **_k: _stub_create_ceo_advisor_agent_with_text(_CEO_INTRO_TEMPLATE),
        raising=True,
    )

    client = TestClient(_load_app())
    body = _post_chat(
        client, prompt="Ko si ti i kako radiš u ovom workspace-u?", session_id="rs_a3"
    )

    txt = str(body.get("text") or "")
    assert "Ja sam CEO Advisor" in txt
    tr = body.get("trace")
    assert isinstance(tr, dict)
    _assert_trace_contract(
        tr,
        triggered=False,
        action="NO_ACTION",
        reason_code="ALLOWLIST_EXPLICIT_META_QUESTION",
        marker_kind="INTERNAL_CEO_INTRO_TEMPLATE",
        allowlisted_this_turn=True,
        redaction_applied=False,
        replacement_applied=False,
        minimal_damage=True,
    )


def test_memory_leak_with_relevant_remainder_redacts(monkeypatch):
    import routers.chat_router as chat_router

    upstream = _MEMORY_TEMPLATE + "\n\nAktivni agenti:\n- ceo_advisor\n- rgo\n"
    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        lambda *_a, **_k: _stub_create_ceo_advisor_agent_with_text(upstream),
        raising=True,
    )

    client = TestClient(_load_app())
    body = _post_chat(
        client, prompt="Koji agenti postoje u sistemu?", session_id="rs_b1"
    )

    txt = str(body.get("text") or "")
    assert "Aktivni agenti" in txt
    assert "ceo_advisor" in txt
    _must_not_contain_any(
        txt,
        [
            "Vrste pamćenja koje koristim",
            "Kratkoročno",
            "Dugoročno",
            "propose → approve → execute",
        ],
    )

    tr = body.get("trace")
    assert isinstance(tr, dict)
    _assert_trace_contract(
        tr,
        triggered=True,
        action="REDACT_LEAKED_SEGMENT",
        reason_code="LEAK_DETECTED_REDACTED",
        marker_kind="INTERNAL_MEMORY_TEMPLATE",
        allowlisted_this_turn=False,
        redaction_applied=True,
        replacement_applied=False,
        minimal_damage=True,
    )


def test_ceo_intro_leak_with_relevant_remainder_redacts(monkeypatch):
    import routers.chat_router as chat_router

    upstream = (
        _CEO_INTRO_TEMPLATE
        + "\n\nEvo 3 slabosti u planu:\n1) KPI nisu jasni\n2) Rizici nisu navedeni\n3) Nema owner/rok\n"
    )
    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        lambda *_a, **_k: _stub_create_ceo_advisor_agent_with_text(upstream),
        raising=True,
    )

    client = TestClient(_load_app())
    body = _post_chat(
        client, prompt="Reci mi 3 slabosti u planu rasta.", session_id="rs_b2"
    )

    txt = str(body.get("text") or "")
    assert "3 slabosti" in txt
    assert "1)" in txt and "2)" in txt and "3)" in txt
    _must_not_contain_any(
        txt, ["Ja sam CEO Advisor u ovom workspace-u", "Kako radim:", "Kako da pitaš:"]
    )

    tr = body.get("trace")
    assert isinstance(tr, dict)
    _assert_trace_contract(
        tr,
        triggered=True,
        action="REDACT_LEAKED_SEGMENT",
        reason_code="LEAK_DETECTED_REDACTED",
        marker_kind="INTERNAL_CEO_INTRO_TEMPLATE",
        allowlisted_this_turn=False,
        redaction_applied=True,
        replacement_applied=False,
        minimal_damage=True,
    )


def test_leak_embedded_mid_answer_redacts_only_segment(monkeypatch):
    import routers.chat_router as chat_router

    upstream = (
        "Preporuka: uradi A pa B.\n\n"
        + _CEO_INTRO_TEMPLATE
        + "\n\nZatim izmjeri rezultat preko KPI."
    )
    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        lambda *_a, **_k: _stub_create_ceo_advisor_agent_with_text(upstream),
        raising=True,
    )

    client = TestClient(_load_app())
    body = _post_chat(client, prompt="Kako da poboljšam plan?", session_id="rs_b3")
    txt = str(body.get("text") or "")

    assert "Preporuka: uradi A pa B." in txt
    assert "Zatim izmjeri rezultat preko KPI." in txt
    _must_not_contain_any(
        txt, ["Ja sam CEO Advisor u ovom workspace-u", "Kako radim:", "Kako da pitaš:"]
    )

    tr = body.get("trace")
    assert isinstance(tr, dict)
    _assert_trace_contract(
        tr,
        triggered=True,
        action="REDACT_LEAKED_SEGMENT",
        reason_code="LEAK_DETECTED_REDACTED",
        marker_kind="INTERNAL_CEO_INTRO_TEMPLATE",
        allowlisted_this_turn=False,
        redaction_applied=True,
        replacement_applied=False,
        minimal_damage=True,
    )


def test_leak_whole_answer_replaces_with_prompt_scoped_clarify_memory(monkeypatch):
    import routers.chat_router as chat_router

    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        lambda *_a, **_k: _stub_create_ceo_advisor_agent_with_text(_MEMORY_TEMPLATE),
        raising=True,
    )

    client = TestClient(_load_app())
    body = _post_chat(
        client, prompt="Koji agenti postoje u sistemu?", session_id="rs_c1"
    )
    txt = str(body.get("text") or "")

    _must_not_contain_any(
        txt,
        [
            "Vrste pamćenja koje koristim",
            "Kratkoročno",
            "Dugoročno",
            "propose → approve → execute",
        ],
    )
    assert "ag" in txt.lower()  # anchor to prompt topic (agenti/agent)
    assert "?" in txt
    assert "Mogu pomoći u read-only modu" not in txt

    tr = body.get("trace")
    assert isinstance(tr, dict)
    _assert_trace_contract(
        tr,
        triggered=True,
        action="REPLACE_WITH_CLARIFY",
        reason_code="LEAK_DETECTED_REPLACED_WITH_CLARIFY",
        marker_kind="INTERNAL_MEMORY_TEMPLATE",
        allowlisted_this_turn=False,
        redaction_applied=False,
        replacement_applied=True,
        minimal_damage=True,
    )


def test_no_false_positive_similar_words_no_trigger(monkeypatch):
    import routers.chat_router as chat_router

    upstream = "Kratkoročno planiranje i dugoročna strategija su oba bitni. Predlažem KPI i rizike."
    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        lambda *_a, **_k: _stub_create_ceo_advisor_agent_with_text(upstream),
        raising=True,
    )

    client = TestClient(_load_app())
    body = _post_chat(client, prompt="Daj mi savjet za planiranje.", session_id="rs_d1")
    assert str(body.get("text") or "") == upstream

    tr = body.get("trace")
    assert isinstance(tr, dict)
    _assert_trace_contract(
        tr,
        triggered=False,
        action="NO_ACTION",
        reason_code="NO_TRIGGER",
        marker_kind="NONE",
        allowlisted_this_turn=False,
        redaction_applied=False,
        replacement_applied=False,
        minimal_damage=True,
    )


def test_stream_non_stream_parity_no_action(monkeypatch):
    import routers.chat_router as chat_router

    monkeypatch.setenv("CHAT_STREAMING_ENABLED", "true")

    clean = (
        "Evo 3 naredna koraka: 1) Definiši KPI 2) Postavi timeline 3) Dodijeli owner-a."
    )
    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        lambda *_a, **_k: _stub_create_ceo_advisor_agent_with_text(clean),
        raising=True,
    )

    client = TestClient(_load_app())
    prompt = "Daj mi 3 naredna koraka za ovaj plan rasta."

    body = _post_chat(client, prompt=prompt, session_id="rs_e3")
    stream_final = _post_chat_stream_final(client, prompt=prompt, session_id="rs_e3")

    assert str(body.get("text") or "") == str(stream_final.get("text") or "")
    assert isinstance(stream_final.get("response"), dict)
    tr_j = body.get("trace")
    tr_s = (stream_final.get("response") or {}).get("trace")
    assert isinstance(tr_j, dict)
    assert isinstance(tr_s, dict)
    assert (tr_j.get("turn_gate") or {}).get("response_sanitizer") == (
        (tr_s.get("turn_gate") or {}).get("response_sanitizer")
    )


def test_stream_non_stream_parity_redact(monkeypatch):
    import routers.chat_router as chat_router

    monkeypatch.setenv("CHAT_STREAMING_ENABLED", "true")

    upstream = _MEMORY_TEMPLATE + "\n\nAktivni agenti:\n- ceo_advisor\n- rgo\n"
    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        lambda *_a, **_k: _stub_create_ceo_advisor_agent_with_text(upstream),
        raising=True,
    )

    client = TestClient(_load_app())
    prompt = "Koji agenti postoje u sistemu?"

    body = _post_chat(client, prompt=prompt, session_id="rs_e1")
    stream_final = _post_chat_stream_final(client, prompt=prompt, session_id="rs_e1")

    assert str(body.get("text") or "") == str(stream_final.get("text") or "")
    assert isinstance(stream_final.get("response"), dict)
    tr_j = body.get("trace")
    tr_s = (stream_final.get("response") or {}).get("trace")
    assert isinstance(tr_j, dict)
    assert isinstance(tr_s, dict)
    assert (tr_j.get("turn_gate") or {}).get("response_sanitizer") == (
        (tr_s.get("turn_gate") or {}).get("response_sanitizer")
    )


def test_stream_non_stream_parity_replace_with_clarify(monkeypatch):
    import routers.chat_router as chat_router

    monkeypatch.setenv("CHAT_STREAMING_ENABLED", "true")

    monkeypatch.setattr(
        chat_router,
        "create_ceo_advisor_agent",
        lambda *_a, **_k: _stub_create_ceo_advisor_agent_with_text(_MEMORY_TEMPLATE),
        raising=True,
    )

    client = TestClient(_load_app())
    prompt = "Koji agenti postoje u sistemu?"

    body = _post_chat(client, prompt=prompt, session_id="rs_e2")
    stream_final = _post_chat_stream_final(client, prompt=prompt, session_id="rs_e2")

    assert str(body.get("text") or "") == str(stream_final.get("text") or "")
    assert isinstance(stream_final.get("response"), dict)
    tr_j = body.get("trace")
    tr_s = (stream_final.get("response") or {}).get("trace")
    assert isinstance(tr_j, dict)
    assert isinstance(tr_s, dict)
    assert (tr_j.get("turn_gate") or {}).get("response_sanitizer") == (
        (tr_s.get("turn_gate") or {}).get("response_sanitizer")
    )
