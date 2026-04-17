import pytest


def test_metrics_persist_is_explicitly_exempt_from_notion_ops_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression lock: metrics persist is a SYSTEM Notion write path.

    Contract decision for /api/ai-ops/metrics/persist:
      - EXEMPT from per-principal Notion Ops ARMED gate by design
      - Must be explicit in code (no accidental bypass)
      - Must use a stable system approval_id for auditable provenance
    """

    import services.metrics_persistence_service as mps

    assert getattr(mps, "NOTION_OPS_GATE_POLICY", None) == "EXEMPT"
    assert getattr(mps, "SYSTEM_METRICS_APPROVAL_ID", None) == "system_metrics_write"

    # Ensure the service emits a Notion write command with the canonical system approval id.
    captured = {}

    class _StubNotionService:
        def execute(self, cmd):
            captured["intent"] = getattr(cmd, "intent", None)
            captured["approval_id"] = getattr(cmd, "approval_id", None)
            captured["params"] = getattr(cmd, "params", None)
            return {"notion_page_id": "page_123"}

    monkeypatch.setenv("NOTION_AGENT_EXCHANGE_DB_KEY", "AgentExchangeDB")
    monkeypatch.setattr(mps, "get_notion_service", lambda: _StubNotionService())
    monkeypatch.setattr(
        mps.MetricsService,
        "snapshot",
        staticmethod(lambda: {"counters": {"x": 1}, "events_by_type": {}}),
    )

    svc = mps.MetricsPersistenceService()
    out = svc.persist_snapshot()

    assert out.get("ok") is True
    assert captured.get("intent") == "create_page"
    assert captured.get("approval_id") == mps.SYSTEM_METRICS_APPROVAL_ID
    assert isinstance(captured.get("params"), dict)
    assert captured["params"].get("db_key") == "AgentExchangeDB"
