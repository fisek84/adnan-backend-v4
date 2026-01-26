from __future__ import annotations

import pytest


@pytest.mark.anyio
async def test_kb_search_normalizes_smart_quotes_and_diacritics(monkeypatch):
    from services.kb_notion_store import NotionKBStore

    store = NotionKBStore(db_id="db", base_url="http://test", cache_ttl_seconds=900)

    entry_id = "kahneman_tfs_002_wysiati"
    phrase_smart = "\u201cOno \u0161to vidi\u0161 je sve \u0161to postoji\u201d"

    async def fake_load_all(*, force: bool = False):
        return {
            "entries": [
                {
                    "id": entry_id,
                    "title": "WYSIATI",
                    "tags": ["psychology", "wysiati"],
                    "content": phrase_smart,
                    "status": "active",
                }
            ],
            "meta": {
                "mode": "notion",
                "source": "notion",
                "total_entries": 1,
                "hash": "test",
            },
        }

    monkeypatch.setattr(store, "load_all", fake_load_all)

    # Query WITHOUT smart quotes and WITHOUT diacritics.
    query = "Ono sto vidis je sve sto postoji"
    out = await store.search(query, top_k=8)

    assert isinstance(out, dict)
    entries = out.get("entries")
    used = out.get("used_entry_ids")

    assert isinstance(entries, list)
    assert isinstance(used, list)
    assert len(entries) == 1
    assert entry_id in used
