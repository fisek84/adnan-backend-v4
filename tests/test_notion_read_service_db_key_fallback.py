import pytest

from services.notion_read_service import NotionReadService


class _FakeNotion:
    def __init__(self):
        self.db_ids = {
            "goals": "db_goals_id",
            "tasks": "db_tasks_id",
            "projects": "db_projects_id",
        }
        self.calls = []

    async def _safe_request(self, method: str, url: str, payload=None):
        self.calls.append({"method": method, "url": url, "payload": payload})

        # Page search returns empty.
        if url == "https://api.notion.com/v1/search" and method == "POST":
            flt = (payload or {}).get("filter") or {}
            if flt.get("value") == "page":
                return {"results": []}
            if flt.get("value") == "database":
                pytest.fail("Should not database-search when query is a DB key")

        # Direct database fetch
        if method == "GET" and url.endswith("/v1/databases/db_goals_id"):
            return {
                "object": "database",
                "title": [{"plain_text": "Ciljevi"}],
                "url": "https://www.notion.so/Ciljevi-123",
            }

        pytest.fail(f"Unexpected request: {method} {url}")


@pytest.mark.anyio
async def test_read_page_as_markdown_db_key_goals_resolves_by_id():
    notion = _FakeNotion()
    svc = NotionReadService(notion)  # type: ignore[arg-type]

    out = await svc.read_page_as_markdown("goals")

    assert out["title"] == "Ciljevi"
    assert out["url"] == "https://www.notion.so/Ciljevi-123"
    assert "Database" in out["content_markdown"]

    # Should do: page search + direct db GET
    assert len(notion.calls) == 2
    assert notion.calls[0]["method"] == "POST"
    assert notion.calls[0]["url"] == "https://api.notion.com/v1/search"
    assert notion.calls[1]["method"] == "GET"
    assert notion.calls[1]["url"].endswith("/v1/databases/db_goals_id")
