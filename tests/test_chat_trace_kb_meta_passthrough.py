from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi.testclient import TestClient

from models.agent_contract import AgentOutput


class _StubKBStore:
    def __init__(self) -> None:
        self._search_calls = 0
        self._last_meta: Dict[str, Any] = {"source": "notion", "cache_hit": False}

    async def get_entries(
        self, ctx: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        # Provide a deterministic loaded KB size.
        return [{"id": f"E{i}", "title": f"T{i}", "content": "x"} for i in range(46)]

    async def search(
        self, query: str, *, top_k: int = 8, force: bool = False
    ) -> Dict[str, Any]:
        self._search_calls += 1
        # /api/chat builds grounding_pack twice per request (pre_grounding + grounding).
        # So we only flip cache_hit after the first *request* has completed.
        cache_hit = self._search_calls > 2
        meta: Dict[str, Any] = {
            "mode": "notion",
            "source": "notion",
            "ttl_s": 60,
            "fetched_at": 123.0,
            "total_entries": 46,
            "cache_hit": cache_hit,
            "hit_count": 0,
            "hits": 0,
        }
        self._last_meta = dict(meta)
        return {"entries": [], "used_entry_ids": [], "meta": meta}

    def get_meta(self) -> Dict[str, Any]:
        return dict(self._last_meta)


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def test_chat_trace_includes_kb_meta_passthrough(monkeypatch) -> None:
    # Ensure grounding pack is enabled so KB retrieval runs.
    monkeypatch.setenv("CEO_GROUNDING_PACK_ENABLED", "true")

    # Requested envs (no real network call should happen; KB store is stubbed).
    monkeypatch.setenv("KB_SOURCE", "notion")
    monkeypatch.setenv("NOTION_KB_DB_ID", "dummy")
    monkeypatch.setenv("KB_TTL_SECONDS", "60")
    monkeypatch.setenv("NOTION_TOKEN", "dummy")

    # Stub KB store factory used by GroundingPackService.
    stub_store = _StubKBStore()

    import services.kb_get_store as kb_get_store  # noqa: PLC0415

    monkeypatch.setattr(kb_get_store, "get_kb_store", lambda: stub_store)

    # Stub the agent to avoid any OpenAI/network behavior; router still builds grounding pack.
    import routers.chat_router as chat_router  # noqa: PLC0415

    async def _fake_agent(*args: Any, **kwargs: Any) -> AgentOutput:
        return AgentOutput(
            text="ok", proposed_commands=[], agent_id="ceo_advisor", trace={}
        )

    monkeypatch.setattr(chat_router, "create_ceo_advisor_agent", _fake_agent)

    app = _get_app()
    client = TestClient(app)

    r1 = client.post(
        "/api/chat",
        json={"message": "debug used_sources", "metadata": {"include_debug": True}},
    )
    assert r1.status_code == 200
    body1 = r1.json()
    assert isinstance(body1, dict)

    # Strict: context.grounding_pack must exist and be a dict (no silent fallbacks).
    ctx1 = body1["context"]
    assert isinstance(ctx1, dict)
    gp_ctx1 = ctx1["grounding_pack"]
    assert isinstance(gp_ctx1, dict)

    tr1 = body1["trace"]
    assert isinstance(tr1, dict)

    assert isinstance(tr1.get("kb_meta"), dict)
    assert tr1["kb_meta"].get("total_entries") == 46
    assert "cache_hit" in tr1["kb_meta"]
    assert tr1["kb_meta"].get("cache_hit") is False

    # Uncheatable passthrough proof: trace must equal context.
    assert tr1["kb_meta"] == gp_ctx1["kb_meta"]

    assert tr1.get("kb_hits") == 0
    assert tr1["kb_hits"] == gp_ctx1["kb_hits"]

    assert tr1.get("kb_used_entry_ids") == []
    assert tr1["kb_used_entry_ids"] == gp_ctx1["kb_used_entry_ids"][:16]

    # Second call should observe cache_hit=True (warm TTL cache behavior).
    r2 = client.post(
        "/api/chat",
        json={"message": "debug used_sources", "metadata": {"include_debug": True}},
    )
    assert r2.status_code == 200
    body2 = r2.json()
    assert isinstance(body2, dict)

    ctx2 = body2["context"]
    assert isinstance(ctx2, dict)
    gp_ctx2 = ctx2["grounding_pack"]
    assert isinstance(gp_ctx2, dict)

    tr2 = body2["trace"]
    assert isinstance(tr2, dict)
    assert isinstance(tr2.get("kb_meta"), dict)
    assert tr2["kb_meta"].get("total_entries") == 46
    assert tr2["kb_meta"].get("cache_hit") is True
    assert tr2.get("kb_hits") == 0
    assert tr2.get("kb_used_entry_ids") == []

    assert tr2["kb_meta"] == gp_ctx2["kb_meta"]
    assert tr2["kb_hits"] == gp_ctx2["kb_hits"]
    assert tr2["kb_used_entry_ids"] == gp_ctx2["kb_used_entry_ids"][:16]
