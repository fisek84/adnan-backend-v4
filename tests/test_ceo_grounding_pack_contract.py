from fastapi.testclient import TestClient


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def test_chat_includes_grounding_pack_contract(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")

    app = _get_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat", json={"message": "Koja je naša operativna filozofija?"}
    )
    assert r.status_code == 200
    body = r.json()

    assert "grounding_pack" in body
    gp = body["grounding_pack"]
    assert isinstance(gp, dict)
    assert gp.get("schema_version") == "v1"

    # Required sub-objects
    assert "identity_pack" in gp and isinstance(gp["identity_pack"], dict)
    assert "kb_snapshot" in gp and isinstance(gp["kb_snapshot"], dict)
    assert "notion_snapshot" in gp and isinstance(gp["notion_snapshot"], dict)
    assert "memory_snapshot" in gp and isinstance(gp["memory_snapshot"], dict)
    assert "diagnostics" in gp and isinstance(gp["diagnostics"], dict)
    assert "trace" in gp and isinstance(gp["trace"], dict)

    # Hashes present (format not strictly asserted)
    assert isinstance(gp["identity_pack"].get("hash"), str)
    assert isinstance(gp["kb_snapshot"].get("hash"), str)
    assert isinstance(gp["memory_snapshot"].get("hash"), str)

    # Deterministic retrieval shape
    kb = gp["kb_snapshot"]
    assert "selected_entries" in kb and isinstance(kb["selected_entries"], list)
    assert "used_entry_ids" in kb and isinstance(kb["used_entry_ids"], list)

    # Enterprise snapshot contract still present
    assert "knowledge_snapshot" in body and isinstance(body["knowledge_snapshot"], dict)
    assert "snapshot_meta" in body and isinstance(body["snapshot_meta"], dict)


def test_ai_run_includes_grounding_pack_contract(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")

    app = _get_app()
    client = TestClient(app)

    r = client.post("/api/ai/run", json={"text": "test"})
    assert r.status_code == 200
    body = r.json()

    assert body.get("ok") is True
    assert body.get("read_only") is True

    assert "grounding_pack" in body
    gp = body["grounding_pack"]
    assert isinstance(gp, dict)
    assert gp.get("schema_version") == "v1"


def test_grounding_pack_can_be_disabled(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "false")

    app = _get_app()
    client = TestClient(app)

    r = client.post("/api/chat", json={"message": "test"})
    assert r.status_code == 200
    body = r.json()

    assert "grounding_pack" in body
    gp = body["grounding_pack"]
    assert isinstance(gp, dict)
    assert gp.get("enabled") is False
    assert isinstance(gp.get("feature_flags"), dict)


def test_kb_only_question_trace_strict(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")

    app = _get_app()
    client = TestClient(app)

    q = "Koja je naša operativna filozofija i zakoni odlučivanja?"
    r = client.post("/api/chat", json={"message": q})
    assert r.status_code == 200
    body = r.json()

    assert "trace_v2" in body
    tr = body["trace_v2"]
    assert isinstance(tr, dict)

    used = tr.get("used_sources")
    assert isinstance(used, list)
    assert "identity_pack" in used
    assert "kb_snapshot" in used

    not_used = tr.get("not_used")
    assert isinstance(not_used, list)
    assert any(
        isinstance(x, dict)
        and x.get("source") == "notion_snapshot"
        and isinstance(x.get("skipped_reason"), str)
        for x in not_used
    )

    assert tr.get("notion_calls") == 0
    read_ids = tr.get("read_ids")
    assert isinstance(read_ids, dict)
    assert read_ids.get("notion") == []


def test_budget_breach_redacts_notion_snapshot(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")
    # Force payload-bytes budget breach deterministically.
    monkeypatch.setenv("CEO_NOTION_MAX_PAYLOAD_BYTES", "1")

    app = _get_app()
    client = TestClient(app)

    r = client.post("/api/chat", json={"message": "Pokaži ciljeve"})
    assert r.status_code == 200
    body = r.json()

    assert "grounding_pack" in body
    gp = body["grounding_pack"]
    assert isinstance(gp, dict)

    # Trace must report budget exceeded.
    tr = body.get("trace_v2")
    assert isinstance(tr, dict)
    assert tr.get("budget_exceeded") is True
    assert isinstance(tr.get("budget_exceeded_detail"), dict)

    # Diagnostics must fall back deterministically.
    diag = body.get("diagnostics")
    assert isinstance(diag, dict)
    mk = diag.get("missing_keys")
    assert isinstance(mk, list)
    assert "notion_budget_exceeded" in mk
    assert diag.get("recommended_action") == "reduce_notion_payload"

    # Grounding notion snapshot must be redacted (no fabricated data).
    ns = gp.get("notion_snapshot")
    assert isinstance(ns, dict)
    meta = ns.get("meta")
    assert isinstance(meta, dict)
    assert meta.get("payload_redacted") is True
    payload = ns.get("payload")
    assert isinstance(payload, dict)
    assert payload.get("goals") == []
    assert payload.get("tasks") == []
    assert payload.get("projects") == []

    # No Notion calls were made by the builder.
    assert tr.get("notion_calls") == 0
