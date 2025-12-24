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
