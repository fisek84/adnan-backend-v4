from __future__ import annotations

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_business_plan_offer_yes_delivers_template_not_json(monkeypatch, tmp_path):
    """Regression: if CEO Advisor explicitly offered a biz plan template, then YES must deliver it."""

    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_bp_offer_yes.json"),
    )

    # Force grounding pack to always include the business-plan KB entry as used.
    from services.grounding_pack_service import GroundingPackService

    def _stub_gp_build(**_k):
        return {
            "enabled": True,
            "identity_pack": {"payload": {"identity": {}}},
            "kb_snapshot": {
                "source": "file",
                "used_entry_ids": ["plans_business_plan_001"],
            },
            "kb_retrieved": {
                "used_entry_ids": ["plans_business_plan_001"],
                "entries": [
                    {
                        "id": "plans_business_plan_001",
                        "title": "Business plan (biznis plan) — kanonski okvir",
                        "content": (
                            "Business plan / biznis plan je strukturirani dokument... "
                            "Ako treba, mogu dati minimalni 1-page template i listu pitanja za popunu."
                        ),
                    }
                ],
            },
            "notion_snapshot": {},
            "memory_snapshot": {"payload": {}},
            "diagnostics": {},
        }

    monkeypatch.setattr(GroundingPackService, "build", staticmethod(_stub_gp_build))

    # Stub the LLM executor:
    # - first call returns KB-backed text that includes the explicit offer sentence
    # - second call must NOT happen (should be bypassed by the pending-offer handler)
    from services.agent_router import executor_factory

    calls = {"n": 0}

    class _DummyExec:
        async def ceo_command(self, text, context):  # noqa: ANN001
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "text": (
                        "Business plan / biznis plan je strukturirani dokument... "
                        "Ako treba, mogu dati minimalni 1-page template i listu pitanja za popunu. "
                        "[KB:plans_business_plan_001]"
                    ),
                    "proposed_commands": [],
                }
            raise AssertionError("LLM must NOT be called on YES-after-offer")

    monkeypatch.setattr(executor_factory, "get_executor", lambda **_k: _DummyExec())

    app = _load_app()
    client = TestClient(app)

    session = "bp-1"

    r1 = client.post(
        "/api/chat",
        json={
            "message": "Treba mi pomoć oko pokretanja biznis plana",
            "metadata": {"include_debug": True},
            "session_id": session,
            "snapshot": {},
        },
    )
    assert r1.status_code == 200, r1.text

    r2 = client.post(
        "/api/chat",
        json={
            "message": "da želim",
            "metadata": {"include_debug": True},
            "session_id": session,
            "snapshot": {},
        },
    )
    assert r2.status_code == 200, r2.text

    body2 = r2.json()
    txt2 = body2.get("text") or ""

    # Must deliver template + questions (plain text).
    assert "BIZNIS PLAN" in txt2
    assert "Problem" in txt2
    assert "Rješenje" in txt2
    assert "Tržište" in txt2
    assert "GTM" in txt2
    assert "Finansije" in txt2
    assert "30/60/90" in txt2
    assert "Pitanja" in txt2

    # Must NOT derail into JSON tooling talk or generic re-asking.
    assert "JSON" not in txt2
    assert "Kako vam mogu pomoći" not in txt2
