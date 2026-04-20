import gc
import warnings

import httpx
import pytest

from main import app


@pytest.mark.anyio
async def test_metrics_persist_does_not_misuse_async_notion_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Avoid any boot-time network sync; this test targets only metrics persist.
    monkeypatch.setenv("GATEWAY_SKIP_KNOWLEDGE_SYNC", "1")

    # Ensure the metrics persistence service is configured.
    monkeypatch.setenv("NOTION_AGENT_EXCHANGE_DB_KEY", "agent_exchange")

    import services.metrics_persistence_service as mps
    import routers.ai_ops_router as aor

    class _StubNotionService:
        async def execute(self, cmd):
            return {"notion_page_id": "page_123"}

    monkeypatch.setattr(mps, "get_notion_service", lambda: _StubNotionService())
    monkeypatch.setattr(
        mps.MetricsService,
        "snapshot",
        staticmethod(lambda: {"counters": {"x": 1}, "events_by_type": {}}),
    )

    # Replace the singleton so it picks up env + patched Notion service.
    aor._metrics_persistence = mps.MetricsPersistenceService()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        headers = {"X-Initiator": "ceo", "X-Session-Id": "sanity-metrics"}

        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always", RuntimeWarning)

            r = await client.post(
                "/api/ai-ops/metrics/persist", json={}, headers=headers
            )
            assert r.status_code == 200
            data = r.json()

            # Force coroutine finalizers to run so 'was never awaited' warnings surface.
            gc.collect()
            gc.collect()

            assert not any(
                "was never awaited" in str(x.message)
                for x in w
                if isinstance(x.message, Warning)
            )

        assert data.get("ok") is True
        assert isinstance(data.get("result"), dict)
        assert data["result"].get("ok") is True
