from __future__ import annotations

import pytest


@pytest.mark.anyio
async def test_kb_search_production_prompt_wysiati_included_and_not_only_hit(
    monkeypatch,
):
    """Regression #2 (production prompt).

    Query: "Objasni WYSIATI kao da sam pročitao knjigu, ali koristi samo KB."

    Requirements:
    - Must include kahneman_tfs_002_wysiati
    - hit_count >= 1
    - must not collapse to only the wrong entry when WYSIATI exists; in this
      fixture, there is at least one additional match, so used_entry_ids must
      contain more than one id.
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
                    # Include non-stopword tokens from the production prompt so this is a valid
                    # secondary match, preventing single-hit collapse in this fixture.
                    "content": "Kao da sam procitao knjigu: framing menja percepciju.",
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

    query = "Objasni WYSIATI kao da sam pročitao knjigu, ali koristi samo KB."
    out = await store.search(query, top_k=8)

    assert isinstance(out, dict)
    used = out.get("used_entry_ids")
    meta = out.get("meta")

    assert isinstance(used, list)
    assert isinstance(meta, dict)

    assert meta.get("hit_count", 0) >= 1
    assert wysiati_id in used

    # In this fixture, framing is also a legitimate match, so do not collapse to a single id.
    assert len(used) >= 2
