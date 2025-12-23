from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


def test_bulk_create_minimal():
    payload = {
        "items": [
            {"type": "goal", "title": "Test Goal A"},
            {"type": "task", "title": "Test Task A", "goal_id": None},
        ]
    }

    response = client.post("/notion-ops/bulk/create", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "created" in data
    assert len(data["created"]) == 2


def test_bulk_update_empty():
    payload = {"updates": []}

    response = client.post("/notion-ops/bulk/update", json=payload)
    assert response.status_code == 200
    assert response.json() == {"updated": []}


def test_bulk_query_empty():
    payload = {"queries": []}

    response = client.post("/notion-ops/bulk/query", json=payload)
    assert response.status_code == 200
    assert response.json() == {"results": []}


def test_bulk_invalid_type():
    payload = {"items": [{"type": "invalid_test_type", "title": "Bad"}]}

    response = client.post("/notion-ops/bulk/create", json=payload)
    assert response.status_code == 400
