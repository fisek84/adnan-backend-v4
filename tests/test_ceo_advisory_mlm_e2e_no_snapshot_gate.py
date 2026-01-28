from __future__ import annotations

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_ceo_advisory_mlm_prompt_does_not_trigger_snapshot_gate(monkeypatch, tmp_path):
    """E2E regression via /api/chat: advisory/thinking MLM prompt must not be blocked by snapshot gate."""

    monkeypatch.setenv("OPENAI_API_KEY", "sk-local")
    monkeypatch.setenv("OPENAI_API_MODE", "responses")
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")
    monkeypatch.setenv(
        "CEO_CONVERSATION_STATE_PATH",
        str(tmp_path / "ceo_conv_state_mlm_1.json"),
    )

    # Keep grounding pack present but minimal; this test is about snapshot-gate bypass.
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

    # IMPORTANT: message must match the real PowerShell repro payload exactly.
    mlm_long = """procitaj ovo reci mi sta mislis i mozel se napraviti od ovog plan

Zelim da iskoristim affiliate/ mlm program - Preko Forever living products kompanije. Trenutno sam na poziciji supevizor i imam 38% popust na proizvode. Moj cilj je da za 90 dana obezbijecim prodajnu mrezu kontinuirani prihod od 3000 USD od prodaje proizvoda. Zelim da kad obezbijedim mrezu kupaca i obezbijedim kontinuiranu masininu prodaje da nudim poslovnu saradnju za saradnike koji zele da se priduze u moju mrezu koristeci MLM Forever living model ali ja kao mentor cu da im obezbijedim model koji je dokazan da radi prodaju itd.. Smatra da je dobro da krenem malim koracim i konkretno a to je da prvi podcilj prema ostvarenju cilja da bude: Prodaja 10 flp proizvoda u 10 dana. Due date 10.02.2026.

Sta mislis
"""

    r = client.post(
        "/api/chat",
        json={
            "message": mlm_long,
            "metadata": {"include_debug": True},
            "session_id": "mlm-1",
            "snapshot": {},
        },
    )
    assert r.status_code == 200, r.text

    body = r.json()
    txt = (body.get("text") or "")
    low = txt.lower()

    # Must not demand snapshot/refresh/READ-context.
    assert "ssot" not in low
    assert "snapshot" not in low
    assert "refresh" not in low
    assert "read kontek" not in low
    assert "ceo console" not in low

    # Must contain a structured plan skeleton.
    assert "Cilj" in txt
    assert "Ponuda" in txt
    assert "Kanali" in txt
    assert "Skripta" in txt
    assert "Dnevne metrike" in txt
    assert "10/30/60/90" in txt
    assert "Rizici" in txt
    assert "Next steps" in txt

    tr = body.get("trace") or {}
    if isinstance(tr, dict):
        assert tr.get("exit_reason") != "fallback.fact_sensitive_no_snapshot"

        gg = tr.get("grounding_gate")
        if isinstance(gg, dict) and ("bypassed" in gg):
            assert gg.get("bypassed") is True
