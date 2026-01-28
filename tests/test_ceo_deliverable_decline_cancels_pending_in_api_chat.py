from __future__ import annotations

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_deliverable_decline_cancels_pending_and_no_unknown_mode(monkeypatch, tmp_path):
    """Regression (E2E): after CEO offers deliverable delegation, 'necu to' must cancel and not fall into unknown_mode."""

    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "1")
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_decline_pending.json"),
    )

    from services.grounding_pack_service import GroundingPackService

    def _stub_gp_build(**_k):
        return {
            "enabled": True,
            "identity_pack": {"payload": {"identity": {}}},
            "kb_snapshot": {"source": "file", "used_entry_ids": []},
            "kb_retrieved": {"used_entry_ids": [], "entries": []},
            "notion_snapshot": {},
            "memory_snapshot": {"payload": {}},
            "diagnostics": {},
        }

    monkeypatch.setattr(GroundingPackService, "build", staticmethod(_stub_gp_build))

    def _boom(*args, **kwargs):  # noqa: ANN001
        raise AssertionError("LLM/executor must not be called")

    monkeypatch.setattr("services.agent_router.executor_factory.get_executor", _boom)

    app = _load_app()
    client = TestClient(app)

    session = "decline-1"

    # Step 1: explicit deliverable request -> must emit proposal-only delegation.
    msg1 = "Napiši mi DM flow (3 poruke) za cold outreach. Rok: sutra."

    r1 = client.post(
        "/api/chat",
        json={
            "message": msg1,
            "metadata": {"include_debug": True},
            "session_id": session,
            "snapshot": {},
        },
    )
    assert r1.status_code == 200, r1.text

    body1 = r1.json()
    txt1 = body1.get("text") or ""
    low1 = txt1.lower()
    assert "želiš da delegiram" in low1
    pcs1 = body1.get("proposed_commands") or []
    assert isinstance(pcs1, list) and len(pcs1) == 1

    # Step 2: user declines.
    r2 = client.post(
        "/api/chat",
        json={
            "message": "NECU TO",
            "metadata": {"include_debug": True},
            "session_id": session,
            "snapshot": {},
        },
    )
    assert r2.status_code == 200, r2.text

    body2 = r2.json()
    txt2 = body2.get("text") or ""
    low2 = txt2.lower()

    assert "ne delegiram" in low2
    assert "trenutno nemam to znanje" not in low2

    pcs2 = body2.get("proposed_commands") or []
    assert pcs2 == []

    tr2 = body2.get("trace") or {}
    if isinstance(tr2, dict):
        assert tr2.get("exit_reason") == "deliverable.declined"


def test_advisory_with_pasted_deliverable_keywords_does_not_offer_delegation(
    monkeypatch, tmp_path
):
    """Regression (E2E): advisory/thinking prompt with pasted 'DM flow (3 poruke)' text must not jump into deliverable delegation."""

    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    # Keep general knowledge OFF so this stays deterministic even if LLM is unavailable.
    monkeypatch.setenv("CEO_ADVISOR_ALLOW_GENERAL_KNOWLEDGE", "0")
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_no_mode_jump.json"),
    )

    from services.grounding_pack_service import GroundingPackService

    def _stub_gp_build(**_k):
        return {
            "enabled": True,
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

    session = "no-mode-jump-1"
    msg = """procitaj ovo reci mi sta mislis

Pasted primjer (nije zahtjev):
- DM flow (3 poruke)
- hookovi
"""

    r = client.post(
        "/api/chat",
        json={
            "message": msg,
            "metadata": {"include_debug": True},
            "session_id": session,
            "snapshot": {},
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    txt = body.get("text") or ""
    low = txt.lower()
    pcs = body.get("proposed_commands") or []

    assert "želiš da delegiram" not in low
    assert pcs == []
