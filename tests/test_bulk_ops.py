import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import sqlalchemy as sa

from main import app


@pytest.fixture
async def client():
    """Async httpx client against the FastAPI ASGI app.

    This avoids httpx's deprecated `app=` shortcut (which Starlette/FastAPI's
    TestClient used historically) and keeps test output warning-free.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
    ) as client:
        yield client


@pytest.mark.anyio
async def test_bulk_create_minimal(client):
    payload = {
        "items": [
            {"type": "goal", "title": "Test Goal A"},
            {"type": "task", "title": "Test Task A", "goal_id": None},
        ]
    }

    response = await client.post("/notion-ops/bulk/create", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "created" in data
    assert len(data["created"]) == 2


@pytest.mark.anyio
async def test_bulk_update_empty(client):
    payload = {"updates": []}

    response = await client.post("/notion-ops/bulk/update", json=payload)
    assert response.status_code == 200
    assert response.json() == {"updated": []}


@pytest.mark.anyio
async def test_bulk_query_empty(client):
    payload = {"queries": []}

    response = await client.post("/notion-ops/bulk/query", json=payload)
    assert response.status_code == 200
    assert response.json() == {"results": []}


@pytest.mark.anyio
async def test_bulk_invalid_type(client):
    payload = {"items": [{"type": "invalid_test_type", "title": "Bad"}]}

    response = await client.post("/notion-ops/bulk/create", json=payload)
    assert response.status_code == 400


@pytest.mark.anyio
@pytest.mark.skipif(
    os.getenv("CI") == "true",
    reason="Full Notion-backed happy-path is skipped in CI (external dependency).",
)
async def test_happy_path_execute_approve(client):
    """
    Canonical HAPPY PATH (isti scenarij kao u test_happy_path.ps1):

    1) POST /api/execute  -> očekujemo BLOCKED + approval_id
    2) GET /api/ai-ops/approval/pending -> approval_id se mora pojaviti u pending listi
    3) POST /api/ai-ops/approval/approve -> očekujemo COMPLETED
    4) (OFL E2E) cron/run -> OFL evaluacija upiše marker za decision_id
    """
    # 1) CEO input -> očekujemo BLOCKED + approval_id
    execute_payload = {"text": "create goal Test Happy Path"}
    response = await client.post("/api/execute", json=execute_payload)
    assert response.status_code == 200

    data = response.json()
    assert data.get("execution_state") == "BLOCKED"
    assert data.get("approval_id"), "approval_id should be present on BLOCKED"
    approval_id = data["approval_id"]

    # 2) Approval mora postojati u pending listi
    pending_response = await client.get("/api/ai-ops/approval/pending")
    assert pending_response.status_code == 200

    pending = pending_response.json()
    approvals = pending.get("approvals", [])
    approval_ids = [a.get("approval_id") for a in approvals]
    assert (
        approval_id in approval_ids
    ), "approval_id from execute must be in pending approvals"

    # 3) Approve -> očekujemo COMPLETED
    approve_response = await client.post(
        "/api/ai-ops/approval/approve",
        json={"approval_id": approval_id},
    )
    assert approve_response.status_code == 200

    approved = approve_response.json()
    assert approved.get("execution_state") == "COMPLETED"

    # -----------------------------
    # 4) OFL E2E (best-effort, requires DB)
    # -----------------------------
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if not db_url:
        pytest.skip("DATABASE_URL not set; skipping OFL DB-backed E2E segment")

    execution_id = approved.get("execution_id")
    assert (
        isinstance(execution_id, str) and execution_id.strip()
    ), "execution_id missing"
    execution_id = execution_id.strip()

    # Get decision_id from DOR
    from services.decision_outcome_registry import get_decision_outcome_registry

    dor = get_decision_outcome_registry()
    dor_rec = dor.get_by_execution_id(execution_id)
    assert isinstance(dor_rec, dict) and dor_rec, "DOR record missing for execution_id"

    decision_id = dor_rec.get("decision_id")
    assert isinstance(decision_id, str) and decision_id.strip(), "decision_id missing"
    decision_id = decision_id.strip()

    # Force OFL rows to be due NOW (so cron can evaluate in this test run)

    engine = sa.create_engine(db_url, pool_pre_ping=True, future=True)
    md = sa.MetaData()
    table = sa.Table("outcome_feedback_loop", md, autoload_with=engine)

    now = datetime.now(timezone.utc)
    due = now - timedelta(seconds=5)

    # Marker column: prefer delta if exists, else kpi_after
    marker_col = None
    if "delta" in table.c:
        marker_col = "delta"
    elif "kpi_after" in table.c:
        marker_col = "kpi_after"
    else:
        pytest.skip("OFL schema missing both delta and kpi_after columns")

    with engine.begin() as conn:
        # Make due + clear marker to ensure evaluate_due_reviews selects these rows
        upd = {
            "review_at": due,
            marker_col: None,
        }
        res = conn.execute(
            sa.update(table).where(table.c["decision_id"] == decision_id).values(**upd)
        )
        assert int(res.rowcount or 0) > 0, "No OFL rows updated for decision_id"

    # Run cron runner (should invoke registered OFL job too)
    cron_response = await client.post("/api/ai-ops/cron/run", json={})
    assert cron_response.status_code == 200
    cron_data = cron_response.json()
    assert cron_data.get("ok") is True

    # Verify at least one OFL row got evaluated (marker not null)
    with engine.begin() as conn:
        sel = (
            sa.select(sa.func.count())
            .select_from(table)
            .where(
                sa.and_(
                    table.c["decision_id"] == decision_id,
                    table.c[marker_col].is_not(None),
                )
            )
        )
        evaluated_count = int(conn.execute(sel).scalar() or 0)

    assert evaluated_count >= 1, "Expected at least one evaluated OFL row"
