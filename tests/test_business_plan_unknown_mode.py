from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient


def _load_app():
    try:
        from gateway.gateway_server import app  # type: ignore

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_api_chat_business_plan_unknown_mode_even_with_snapshot_present(
    monkeypatch, tmp_path: Path
):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")

    # Force a KB that does NOT include plans_business_plan_001.
    kb_path = tmp_path / "knowledge.json"
    kb_path.write_text(
        json.dumps(
            {
                "version": "test",
                "description": "test kb without business plan entry",
                "entries": [
                    {
                        "id": "roles_001",
                        "title": "Uloge agenata: CEO Advisor i Notion Ops",
                        "tags": ["agents", "roles", "capabilities"],
                        "applies_to": ["all"],
                        "priority": 1.0,
                        "content": "CEO Advisor: chat + plan + analiza.",
                        "updated_at": "2026-01-22",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("IDENTITY_KNOWLEDGE_PATH", str(kb_path))

    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "Dali znas za bilo kakav biznis plan za ovaj sistem?",
            "identity_pack": {"user_id": "test"},
            # present_in_request must be true, but without business facts.
            "snapshot": {"meta": {"present_in_request": True}},
            "metadata": {"include_debug": True},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    txt = body.get("text") or ""
    assert "GOALS (top 3)" not in txt
    assert "TASKS (top 5)" not in txt
    assert "Ne mogu dati smislen odgovor" in txt

    gp = body.get("grounding_pack")
    assert isinstance(gp, dict)
    diag = gp.get("diagnostics")
    assert isinstance(diag, dict)
    missing = diag.get("missing_keys")
    assert isinstance(missing, list)
    assert "plans_business_plan_001" in missing
    assert diag.get("recommended_action") == "add_identity_kb_entry"


def test_kb_retrieval_no_false_positive_roles_for_business_plan(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")

    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "biznis plan",
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
            "metadata": {"include_debug": True},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    gp = body.get("grounding_pack")
    assert isinstance(gp, dict)
    kb = gp.get("kb_snapshot")
    assert isinstance(kb, dict)
    used_ids = kb.get("used_entry_ids")
    assert isinstance(used_ids, list)

    # Must NOT be a false positive where roles_001 is the only match.
    assert used_ids != ["roles_001"]


def test_snapshot_budget_default_min_calls(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")

    app = _load_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "ping",
            "identity_pack": {"user_id": "test"},
            "snapshot": {},
            "metadata": {"include_debug": True},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    tr = body.get("trace_v2")
    assert isinstance(tr, dict)
    budgets = tr.get("budgets")
    assert isinstance(budgets, dict)
    notion = budgets.get("notion")
    assert isinstance(notion, dict)

    assert int(notion.get("max_calls")) >= 3
