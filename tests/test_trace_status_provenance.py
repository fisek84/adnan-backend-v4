from __future__ import annotations

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_provenance_query_does_not_trigger_memory_governance(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")

    app = _load_app()
    client = TestClient(app)

    prompt = (
        "Koji je tvoj tačan status izvora znanja za ovo pitanje: "
        "KB/Identity/Memory/Notion (šta je korišteno, šta je preskočeno i zašto)?"
    )

    r = client.post(
        "/api/chat",
        json={"message": prompt, "identity_pack": {"user_id": "test"}, "snapshot": {}},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    txt = body.get("text") or ""
    assert "kori" in txt.lower()  # korišteno / koristio
    assert "presko" in txt.lower()  # preskočeno

    # Must NOT include memory governance instructions or bracket tags.
    assert "zapamti" not in txt.lower()
    assert "proširi" not in txt.lower() and "prosiri" not in txt.lower()
    assert "[kb:" not in txt.lower()
    assert "[id:" not in txt.lower()

    # Should reflect trace_v2 sources deterministically.
    assert "identity_pack" in txt
    assert "kb_snapshot" in txt
    assert "notion_snapshot" in txt
    assert "targeted_reads_disabled" in txt
    assert "memory_snapshot" in txt
    assert "not_required_for_prompt" in txt

    # Legacy trace intent must be trace_status (not memory_or_expand_knowledge)
    tr = body.get("trace")
    assert isinstance(tr, dict)
    assert tr.get("intent") == "trace_status"


def test_zapamti_and_prosiri_znanje_still_trigger_memory_flow(monkeypatch):
    from models.canon import PROPOSAL_WRAPPER_INTENT

    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")

    app = _load_app()
    client = TestClient(app)

    for msg in (
        "Zapamti ovo: test note",
        "Proširi znanje: business plan template",
    ):
        r = client.post(
            "/api/chat",
            json={"message": msg, "identity_pack": {"user_id": "test"}, "snapshot": {}},
        )
        assert r.status_code == 200, r.text
        body = r.json()
        pcs = body.get("proposed_commands") or []
        assert isinstance(pcs, list) and pcs

        pc0 = pcs[0]
        assert isinstance(pc0, dict)
        assert pc0.get("command") == PROPOSAL_WRAPPER_INTENT
        assert pc0.get("intent") == "memory_write"
        args = pc0.get("args")
        assert isinstance(args, dict)
        assert args.get("schema_version") == "memory_write.v1"
        assert args.get("approval_required") is True
        assert "prompt" not in args
