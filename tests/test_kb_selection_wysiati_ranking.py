from __future__ import annotations

import pytest


@pytest.mark.anyio
async def test_kb_search_prefers_wysiati_over_stopword_overlap(monkeypatch):
    """Regression: prompts like 'Objasni WYSIATI kao da sam dete' must not
    drop the WYSIATI entry due to >=2-token gating or get hijacked by entries
    that only match prompt stopwords.
    """

    from services.kb_notion_store import NotionKBStore

    store = NotionKBStore(db_id="db", base_url="http://test", cache_ttl_seconds=900)

    wysiati_id = "kahneman_tfs_002_wysiati"
    framing_id = "kahneman_tfs_011_framing"

    async def fake_load_all(*, force: bool = False):
        return {
            "entries": [
                {
                    "id": framing_id,
                    "title": "Framing",
                    "tags": ["psychology"],
                    # Intentionally includes common prompt words to reproduce the prior bad ranking.
                    "content": "Objasni kao da sam dete. Ovo je samo primer.",
                    "status": "active",
                },
                {
                    "id": wysiati_id,
                    "title": "WYSIATI",
                    "tags": ["psychology", "wysiati"],
                    "content": "Ono sto vidis je sve sto postoji.",
                    "status": "active",
                },
            ],
            "meta": {
                "mode": "notion",
                "source": "notion",
                "total_entries": 2,
                "hash": "test",
            },
        }

    monkeypatch.setattr(store, "load_all", fake_load_all)

    query = "Objasni WYSIATI kao da sam dete"
    out = await store.search(query, top_k=8)

    assert isinstance(out, dict)
    used = out.get("used_entry_ids")
    assert isinstance(used, list)

    # Must include WYSIATI, and it should win the top slot.
    assert wysiati_id in used
    assert used[0] == wysiati_id
