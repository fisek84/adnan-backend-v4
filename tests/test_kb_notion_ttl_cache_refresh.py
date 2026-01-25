from __future__ import annotations

import asyncio


def _run(coro):
    return asyncio.run(coro)


def test_kb_notion_store_ttl_cache_refresh(monkeypatch):
    from services import kb_notion_store as mod

    mod._reset_cache_for_tests()

    store = mod.KBNotionStore(db_id="db_test", cache_ttl_seconds=10)

    calls = {"n": 0}

    async def _fake_fetch():
        calls["n"] += 1
        n = calls["n"]
        entries = [
            {
                "id": f"kb_{n}",
                "title": "T",
                "tags": [],
                "applies_to": ["all"],
                "priority": 0.5,
                "content": f"C{n}",
                "updated_at": None,
            }
        ]
        return entries, f"hash_{n}", f"2026-01-01T00:00:0{n}Z"

    monkeypatch.setattr(store, "_fetch_entries_with_retry", _fake_fetch)

    monkeypatch.setattr(mod.time, "time", lambda: 1000.0)
    out1 = _run(store.load_all(force=False))
    assert calls["n"] == 1
    assert isinstance(out1, dict)
    assert out1.get("meta", {}).get("cache_hit") is False
    assert out1.get("meta", {}).get("hash") == "hash_1"

    # Within TTL -> cache hit, no second fetch.
    monkeypatch.setattr(mod.time, "time", lambda: 1005.0)
    out2 = _run(store.load_all(force=False))
    assert calls["n"] == 1
    assert out2.get("meta", {}).get("cache_hit") is True
    assert out2.get("meta", {}).get("hash") == "hash_1"

    # After TTL -> refresh fetch.
    monkeypatch.setattr(mod.time, "time", lambda: 1011.0)
    out3 = _run(store.load_all(force=False))
    assert calls["n"] == 2
    assert out3.get("meta", {}).get("cache_hit") is False
    assert out3.get("meta", {}).get("hash") == "hash_2"
