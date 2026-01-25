from __future__ import annotations

from fastapi.testclient import TestClient


def _get_app():
    try:
        from gateway.gateway_server import app  # noqa: PLC0415

        return app
    except Exception:
        from main import app  # type: ignore

        return app


def test_chat_trace_shows_kb_loaded_even_when_no_hits(monkeypatch):
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")

    class FakeKBStore:
        async def get_entries(self, ctx=None):
            # Non-empty KB so kb_snapshot is present/ok.
            return [
                {
                    "id": "kb_a",
                    "title": "A",
                    "tags": [],
                    "applies_to": ["all"],
                    "priority": 0.5,
                    "content": "alpha",
                    "updated_at": None,
                },
                {
                    "id": "kb_b",
                    "title": "B",
                    "tags": [],
                    "applies_to": ["all"],
                    "priority": 0.5,
                    "content": "beta",
                    "updated_at": None,
                },
            ]

        async def search(self, query: str, *, top_k: int = 8, force: bool = False):
            return {
                "entries": [],
                "used_entry_ids": [],
                "meta": {
                    "mode": "notion",
                    "ttl_s": 60,
                    "fetched_at": 0.0,
                    "last_fetch_iso": "2026-01-01T00:00:00Z",
                    "total_entries": 2,
                    "hit_count": 0,
                    "hash": "hash_test",
                },
            }

        def get_meta(self):
            return {
                "source": "notion",
                "cache_hit": True,
                "last_sync": "2026-01-01T00:00:00Z",
            }

    monkeypatch.setattr("services.kb_get_store.get_kb_store", lambda: FakeKBStore())

    app = _get_app()
    client = TestClient(app)

    r = client.post(
        "/api/chat",
        json={
            "message": "unmatched query",
            "metadata": {"include_debug": True},
            "snapshot": {},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    tr = body.get("trace")
    assert isinstance(tr, dict)

    assert isinstance(tr.get("kb_meta"), dict)
    assert tr.get("kb_loaded_total") == 2
    assert tr.get("kb_hits") == 0
    assert tr.get("kb_ids_used") == []
    assert tr.get("kb_entries_injected") == 0
