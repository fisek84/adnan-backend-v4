from __future__ import annotations

from services.kb_notion_store import map_notion_page_to_kb_entry


def _page(*, status: str, source: str | None = None):
    props = {
        "Status": {"select": {"name": status}},
        "Name": {"title": [{"plain_text": "T"}]},
        "ID": {"rich_text": [{"plain_text": "kb_1"}]},
        "Tags": {"multi_select": [{"name": "system"}]},
        "AppliesTo": {"multi_select": [{"name": "all"}]},
        "Priority": {"number": 0.5},
        "Content": {"rich_text": [{"plain_text": "C"}]},
    }
    if source is not None:
        props["Source"] = {"select": {"name": source}}

    return {
        "properties": props,
        "last_edited_time": "2026-01-01T00:00:00.000Z",
    }


def test_kb_notion_store_status_filter_is_case_insensitive(monkeypatch):
    monkeypatch.delenv("KB_ALLOWED_SOURCES", raising=False)

    assert map_notion_page_to_kb_entry(_page(status="Active")) is not None
    assert map_notion_page_to_kb_entry(_page(status="active")) is not None
    assert map_notion_page_to_kb_entry(_page(status="INACTIVE")) is None


def test_kb_notion_store_source_allowlist_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("KB_ALLOWED_SOURCES", "book,system")

    assert (
        map_notion_page_to_kb_entry(_page(status="active", source="system")) is not None
    )
    assert (
        map_notion_page_to_kb_entry(_page(status="active", source="BOOK")) is not None
    )
    assert map_notion_page_to_kb_entry(_page(status="active", source="manual")) is None


def test_kb_notion_store_source_allowlist_can_include_manual(monkeypatch):
    monkeypatch.setenv("KB_ALLOWED_SOURCES", "book,system,manual")

    assert (
        map_notion_page_to_kb_entry(_page(status="active", source="manual")) is not None
    )
