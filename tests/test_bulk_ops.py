import httpx
import pytest

from main import app


@pytest.fixture
async def client():
    """Async httpx client against the FastAPI ASGI app.

    This avoids httpx's deprecated `app=` shortcut (which Starlette/FastAPI's
    TestClient used historically) and keeps test output warning-free.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
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
async def test_happy_path_execute_approve(client):
    """
    Canonical HAPPY PATH (isti scenarij kao u test_happy_path.ps1):

    1) POST /api/execute  -> očekujemo BLOCKED + approval_id
    2) GET /api/ai-ops/approval/pending -> approval_id se mora pojaviti u pending listi
    3) POST /api/ai-ops/approval/approve -> očekujemo COMPLETED
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
