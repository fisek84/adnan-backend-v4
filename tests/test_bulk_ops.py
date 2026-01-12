import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import sqlalchemy as sa

from main import app


@pytest.fixture
async def client():
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.mark.anyio
async def test_bulk_create_minimal(client):
    payload = {
        "items": [
            {"type": "goal", "title": "Test Goal A"},
            {"type": "task", "title": "Test Task A", "goal_id": None},
        ]
    }
    r = await client.post("/notion-ops/bulk/create", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert "created" in data
    assert len(data["created"]) == 2


@pytest.mark.anyio
async def test_bulk_update_empty(client):
    payload = {"updates": []}
    r = await client.post("/notion-ops/bulk/update", json=payload)
    assert r.status_code == 200
    assert r.json() == {"updated": []}


@pytest.mark.anyio
async def test_bulk_query_empty(client):
    payload = {"queries": []}
    r = await client.post("/notion-ops/bulk/query", json=payload)
    assert r.status_code == 200
    assert r.json() == {"results": []}


@pytest.mark.anyio
async def test_bulk_invalid_type(client):
    payload = {"items": [{"type": "invalid_test_type", "title": "Bad"}]}
    r = await client.post("/notion-ops/bulk/create", json=payload)
    assert r.status_code == 400


def _env_true(name: str, default: str = "false") -> bool:
    return (os.getenv(name, default) or "").strip().lower() == "true"


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

    NOTE: ovaj test je OPT-IN jer pravi Notion write može failati lokalno zbog permisa/DB mappinga;
          pokreće se samo ako HAPPY_PATH_LIVE_NOTION=true.
    """
    if not _env_true("HAPPY_PATH_LIVE_NOTION", "false"):
        pytest.skip("Set HAPPY_PATH_LIVE_NOTION=true to run live Notion happy-path")

    # minimal env sanity (da ne dobijemo lažne FAIL-ove)
    required = [
        "OPENAI_API_KEY",
        "NOTION_API_KEY",
        "NOTION_GOALS_DB_ID",
        "NOTION_TASKS_DB_ID",
        "NOTION_PROJECTS_DB_ID",
    ]
    missing = [k for k in required if not (os.getenv(k) or "").strip()]
    if missing:
        pytest.skip(f"Missing required env for live happy-path: {', '.join(missing)}")

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
    assert approval_id in approval_ids, "approval_id from execute must be in pending approvals"

    # 3) Approve -> očekujemo COMPLETED
    approve_response = await client.post(
        "/api/ai-ops/approval/approve",
        json={"approval_id": approval_id},
    )
    assert approve_response.status_code == 200

    approved = approve_response.json()
    assert approved.get("execution_state") == "COMPLETED", f"approve failed: {approved}"

    # -----------------------------
    # 4) OFL E2E (best-effort, requires DB)
    # -----------------------------
    db_url = (os.getenv("DATABASE_URL") or "").strip()
    if not db_url:
        pytest.skip("DATABASE_URL not set; skipping OFL DB-backed E2E segment")

    execution_id = approved.get("execution_id")
    assert isinstance(execution_id, str) and execution_id.strip(), "execution_id missing"
    execution_id = execution_id.strip()

    # Get decision_id from DOR
    from services.decision_outcome_registry import get_decision_outcome_registry

    dor = get_decision_outcome_registry()
    dor_rec = dor.get_by_execution_id(execution_id)
    assert isinstance(dor_rec, dict) and dor_rec, "DOR record missing for execution_id"

    decision_id = dor_rec.get("decision_id")
    assert isinstance(decision_id, str) and decision_id.strip(), "decision_id missing"
    decision_id = decision_id.strip()

    engine = sa.create_engine(db_url, pool_pre_ping=True, future=True)
    md = sa.MetaData()
    table = sa.Table("outcome_feedback_loop", md, autoload_with=engine)

    now = datetime.now(timezone.utc)
    due = now - timedelta(seconds=5)

    marker_col = "delta" if "delta" in table.c else ("kpi_after" if "kpi_after" in table.c else None)
    if marker_col is None:
        pytest.skip("OFL schema missing both delta and kpi_after columns")

    with engine.begin() as conn:
        res = conn.execute(
            sa.update(table)
            .where(table.c["decision_id"] == decision_id)
            .values(**{"review_at": due, marker_col: None})
        )
        assert int(res.rowcount or 0) > 0, "No OFL rows updated for decision_id"

    cron_response = await client.post("/api/ai-ops/cron/run", json={})
    assert cron_response.status_code == 200
    cron_data = cron_response.json()
    assert cron_data.get("ok") is True, f"cron/run failed: {cron_data}"

    with engine.begin() as conn:
        evaluated_count = int(
            conn.execute(
                sa.select(sa.func.count())
                .select_from(table)
                .where(
                    sa.and_(
                        table.c["decision_id"] == decision_id,
                        table.c[marker_col].is_not(None),
                    )
                )
            ).scalar()
            or 0
        )

    assert evaluated_count >= 1, "Expected at least one evaluated OFL row"
