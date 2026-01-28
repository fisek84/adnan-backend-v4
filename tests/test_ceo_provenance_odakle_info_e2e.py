from __future__ import annotations

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_api_chat_provenance_odakle_info_does_not_return_unknown_mode(monkeypatch, tmp_path):
    """E2E regression: provenance questions must not fall back to unknown_mode.

    Scenario:
    1) Send an advisory/coaching message that gets a deterministic coaching response.
    2) Ask 'odakle ti info...' -> must return provenance text, not 'Trenutno nemam to znanje...'.
    3) Ask 'izvor?' -> same.
    """

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_provenance_1.json"),
    )

    from services.grounding_pack_service import GroundingPackService

    def _stub_gp_build(**_k):
        # No curated sources used in this test; we want the explicit "iz tvog inputa" provenance message.
        return {
            "enabled": True,
            "trace": {"used_sources": [], "not_used": []},
            "identity_pack": {"payload": {"identity": {}}},
            "kb_snapshot": {"source": "file", "used_entry_ids": []},
            "kb_retrieved": {"used_entry_ids": [], "entries": []},
            "notion_snapshot": {},
            "memory_snapshot": {"payload": {}},
            "diagnostics": {},
        }

    monkeypatch.setattr(GroundingPackService, "build", staticmethod(_stub_gp_build))

    app = _load_app()
    client = TestClient(app)

    session_id = "prov-1"

    # Step 1: advisory/coaching prompt (deterministic coaching flow).
    msg1 = "procitaj ovo reci mi sta mislis i mozel se napraviti od ovog plan\n\nSta mislis"
    r1 = client.post(
        "/api/chat",
        json={
            "message": msg1,
            "metadata": {"include_debug": True},
            "session_id": session_id,
            "snapshot": {},
        },
    )
    assert r1.status_code == 200, r1.text

    # Step 2: provenance question
    r2 = client.post(
        "/api/chat",
        json={
            "message": "odakle ti info koji si podijelio?",
            "metadata": {"include_debug": True},
            "session_id": session_id,
            "snapshot": {},
        },
    )
    assert r2.status_code == 200, r2.text
    txt2 = (r2.json().get("text") or "").lower()
    assert "trenutno nemam to znanje" not in txt2
    assert ("korišteno:" in txt2) or ("used:" in txt2) or ("iz tvog inputa" in txt2)

    # Step 3: short variant
    r3 = client.post(
        "/api/chat",
        json={
            "message": "izvor?",
            "metadata": {"include_debug": True},
            "session_id": session_id,
            "snapshot": {},
        },
    )
    assert r3.status_code == 200, r3.text
    txt3 = (r3.json().get("text") or "").lower()
    assert "trenutno nemam to znanje" not in txt3
    assert ("korišteno:" in txt3) or ("used:" in txt3) or ("iz tvog inputa" in txt3)
