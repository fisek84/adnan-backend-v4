from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import pytest

from services.grounding_pack_service import GroundingPackService


class _DummyKBStore:
    def __init__(self, *, entries: List[Dict[str, Any]], used_ids: List[str]):
        self._entries = entries
        self._used_ids = used_ids

    async def search(self, query: str, *, top_k: int = 8, force: bool = False) -> Dict[str, Any]:
        # Simulate a store implementation that returns hits/ids but forgets to emit `meta`.
        # This previously caused grounding_pack.kb_retrieved.meta (and downstream trace.kb_meta)
        # to be empty.
        return {
            "entries": list(self._entries),
            "used_entry_ids": list(self._used_ids),
            "meta": None,
        }


@pytest.mark.parametrize(
    "selected_entries,used_ids",
    [
        ([{"id": "kb_1", "title": "T", "content": "C"}], ["kb_1"]),
        ([], []),
    ],
)
def test_grounding_pack_kb_search_meta_falls_back_to_loader_meta(
    monkeypatch, selected_entries: List[Dict[str, Any]], used_ids: List[str]
) -> None:
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")

    kb_store = _DummyKBStore(entries=selected_entries, used_ids=used_ids)
    kb_file = {
        "version": "notion",
        "description": "kb",
        "entries": [
            {"id": "kb_1", "title": "T", "content": "C"},
            {"id": "kb_2", "title": "T2", "content": "C2"},
        ],
    }
    kb_meta = {
        "mode": "notion",
        "source": "notion",
        "ttl_s": 60,
        "fetched_at": 123.0,
        "last_fetch_iso": "2026-01-01T00:00:00Z",
        "total_entries": 2,
        "cache_hit": True,
    }

    def _fake_load_kb_file(*, ctx: Optional[Dict[str, Any]] = None) -> Tuple[Dict[str, Any], Dict[str, Any], Any]:
        return kb_file, kb_meta, kb_store

    monkeypatch.setattr(GroundingPackService, "_load_kb_file", _fake_load_kb_file)
    monkeypatch.setattr(GroundingPackService, "_load_identity_pack", lambda: {"available": True})

    out = GroundingPackService.build(
        prompt="test prompt",
        knowledge_snapshot={"payload": {"goals": [], "tasks": [], "projects": []}},
        memory_public_snapshot={},
        legacy_trace=None,
        agent_id="pytest",
    )

    kb = out.get("kb_retrieved")
    assert isinstance(kb, dict)

    assert kb.get("entries") == selected_entries
    assert kb.get("used_entry_ids") == used_ids

    meta = kb.get("meta")
    assert isinstance(meta, dict)

    # Must not be empty even when store.search() forgot to emit `meta`.
    assert meta.get("source") == "notion"
    assert meta.get("mode") == "notion"
    assert meta.get("total_entries") == 2
    assert meta.get("hits") == len(selected_entries)
    assert meta.get("hit_count") == len(selected_entries)

    tr = out.get("trace")
    assert isinstance(tr, dict)
    assert isinstance(tr.get("kb_meta"), dict)
    assert tr.get("kb_meta", {}).get("total_entries") == 2
    assert tr.get("kb_hits") == len(selected_entries)
    assert tr.get("kb_used_entry_ids") == used_ids[:16]
