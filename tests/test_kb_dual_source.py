import sys
import json
import asyncio

import pytest
import httpx


def test_file_store_defaults_and_invalid_entries(tmp_path, monkeypatch):
    from services.kb_file_store import FileKBStore

    kb_path = tmp_path / "kb.json"
    kb_path.write_text(
        json.dumps(
            {
                "version": "1",
                "entries": [
                    {"id": "ok1", "content": "c1"},
                    {"id": "bad1"},
                    {"content": "no-id"},
                    "not-a-dict",
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("IDENTITY_KNOWLEDGE_PATH", str(kb_path))

    store = FileKBStore()
    payload, entries = store.load_payload_and_entries()

    assert payload.get("version") == "1"
    assert isinstance(entries, list)
    assert len(entries) == 1

    e = entries[0]
    assert e["id"] == "ok1"
    assert e["content"] == "c1"
    assert e["title"] == ""
    assert e["tags"] == []
    assert e["applies_to"] == ["all"]
    assert e["priority"] == 0.5
    assert e["updated_at"] is None


def test_notion_mapping_and_status_skip():
    from services.kb_notion_store import map_notion_page_to_kb_entry

    page_active = {
        "last_edited_time": "2026-01-01T00:00:00.000Z",
        "properties": {
            "Name": {"title": [{"plain_text": "T"}]},
            "ID": {"rich_text": [{"plain_text": "id1"}]},
            "Tags": {"multi_select": [{"name": "a"}, {"name": "b"}]},
            "AppliesTo": {"multi_select": []},
            "Priority": {"number": 0.9},
            "Content": {
                "rich_text": [{"plain_text": "line1"}, {"plain_text": "line2"}]
            },
            "UpdatedAt": {"date": {"start": "2026-01-02"}},
            "Status": {"select": {"name": "active"}},
        },
    }

    e = map_notion_page_to_kb_entry(page_active)
    assert e is not None
    assert e["id"] == "id1"
    assert e["title"] == "T"
    assert e["tags"] == ["a", "b"]
    assert e["applies_to"] == ["all"]
    assert e["priority"] == 0.9
    assert e["content"] == "line1\nline2"
    assert e["updated_at"] == "2026-01-02"

    page_inactive = {
        "properties": {
            "Name": {"title": [{"plain_text": "T"}]},
            "ID": {"rich_text": [{"plain_text": "id2"}]},
            "Content": {"rich_text": [{"plain_text": "x"}]},
            "Status": {"select": {"name": "inactive"}},
        }
    }
    assert map_notion_page_to_kb_entry(page_inactive) is None

    page_inactive_status_type = {
        "properties": {
            "Name": {"title": [{"plain_text": "T"}]},
            "ID": {"rich_text": [{"plain_text": "id3"}]},
            "Content": {"rich_text": [{"plain_text": "x"}]},
            "Status": {"status": {"name": "inactive"}},
        }
    }
    assert map_notion_page_to_kb_entry(page_inactive_status_type) is None


@pytest.mark.anyio
async def test_notion_singleflight_one_http_call(monkeypatch):
    from services.kb_notion_store import NotionKBStore, _reset_cache_for_tests

    _reset_cache_for_tests()

    monkeypatch.setenv("NOTION_TOKEN", "test-token")

    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        assert request.method == "POST"
        assert request.url.path.endswith("/query")
        body = {
            "results": [
                {
                    "last_edited_time": "2026-01-01T00:00:00.000Z",
                    "properties": {
                        "Name": {"title": [{"plain_text": "T"}]},
                        "ID": {"rich_text": [{"plain_text": "id1"}]},
                        "Tags": {"multi_select": []},
                        "AppliesTo": {"multi_select": []},
                        "Priority": {"number": 0.5},
                        "Content": {"rich_text": [{"plain_text": "c"}]},
                        "Status": {"select": {"name": "active"}},
                    },
                }
            ],
            "has_more": False,
            "next_cursor": None,
        }
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)

    store = NotionKBStore(
        db_id="db",
        base_url="http://test",
        cache_ttl_seconds=900,
        transport=transport,
    )

    async def call_once():
        return await store.get_entries({"request_id": "r1"})

    out = await asyncio.gather(*[call_once() for _ in range(10)])
    assert calls["n"] == 1
    assert len(out) == 10
    assert out[0] and out[-1]


def test_file_mode_retrieval_matches_raw_loader(monkeypatch):
    from services.grounding_pack_service import GroundingPackService
    from services.identity_loader import load_json_file, resolve_path

    monkeypatch.delenv("KB_SOURCE", raising=False)
    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")

    kb_raw = load_json_file(resolve_path("knowledge.json"))
    baseline = GroundingPackService._retrieve_kb(
        prompt="notion ops approval dispatch", kb=kb_raw
    )

    gp = GroundingPackService.build(
        prompt="notion ops approval dispatch",
        knowledge_snapshot={},
        memory_public_snapshot={},
        legacy_trace=None,
        agent_id="ceo_advisor",
    )

    used = gp.get("kb_snapshot", {}).get("used_entry_ids")
    assert used == baseline.used_entry_ids


@pytest.mark.anyio
async def test_kb_source_notion_success_and_fallback(monkeypatch):
    from services.kb_get_store import get_kb_store
    from services.kb_notion_store import NotionKBStore, _reset_cache_for_tests

    _reset_cache_for_tests()

    monkeypatch.setenv("KB_SOURCE", "notion")
    monkeypatch.setenv("NOTION_KB_DB_ID", "db")
    monkeypatch.setenv("NOTION_TOKEN", "test-token")

    # success transport
    def ok_handler(request: httpx.Request) -> httpx.Response:
        body = {
            "results": [
                {
                    "last_edited_time": "2026-01-01T00:00:00.000Z",
                    "properties": {
                        "Name": {"title": [{"plain_text": "T"}]},
                        "ID": {"rich_text": [{"plain_text": "id1"}]},
                        "Tags": {"multi_select": []},
                        "AppliesTo": {"multi_select": []},
                        "Priority": {"number": 0.5},
                        "Content": {"rich_text": [{"plain_text": "c"}]},
                        "Status": {"select": {"name": "active"}},
                    },
                }
            ],
            "has_more": False,
            "next_cursor": None,
        }
        return httpx.Response(200, json=body)

    ok_store = NotionKBStore(
        db_id="db", base_url="http://test", transport=httpx.MockTransport(ok_handler)
    )

    import services.kb_get_store as kb_get_store

    kb_get_store._NOTION_STORE = ok_store
    kb_get_store._FALLBACK_STORE = None

    store = get_kb_store()
    entries = await store.get_entries({"request_id": "r1"})
    meta = store.get_meta()
    assert meta.get("source") == "notion"
    assert len(entries) > 0

    # failing transport -> file fallback
    def fail_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    _reset_cache_for_tests()
    fail_store = NotionKBStore(
        db_id="db", base_url="http://test", transport=httpx.MockTransport(fail_handler)
    )
    kb_get_store._NOTION_STORE = fail_store
    kb_get_store._FALLBACK_STORE = None

    store2 = get_kb_store()
    entries2 = await store2.get_entries({"request_id": "r2"})
    meta2 = store2.get_meta()
    assert meta2.get("source") == "file_fallback"
    assert isinstance(entries2, list)


def test_kb_does_not_import_notion_sync_service(monkeypatch):
    from services.grounding_pack_service import GroundingPackService

    monkeypatch.setenv("CEO_NOTION_TARGETED_READS_ENABLED", "false")

    # Other tests may import this module; we specifically guard that KB retrieval
    # does not import it.
    sys.modules.pop("services.notion_sync_service", None)

    GroundingPackService.build(
        prompt="hello",
        knowledge_snapshot={},
        memory_public_snapshot={},
        legacy_trace=None,
        agent_id="ceo_advisor",
    )

    assert "services.notion_sync_service" not in sys.modules
