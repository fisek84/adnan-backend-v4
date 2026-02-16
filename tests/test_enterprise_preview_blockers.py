import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _enable_enterprise_preview_editor(monkeypatch):
    # Needed to exercise server-side patches=[{op_id, changes}] path.
    monkeypatch.setenv("ENTERPRISE_PREVIEW_EDITOR", "1")
    yield


def _find_issue_for_op(issues, *, op_id: str, field: str, code: str):
    for it in issues or []:
        if not isinstance(it, dict):
            continue
        if (it.get("op_id") or "") != op_id:
            continue
        if (it.get("field") or "") != field:
            continue
        if (it.get("code") or "") != code:
            continue
        return it
    return None


def test_preview_has_blockers_and_can_approve_false_for_invalid_level():
    from gateway.gateway_server import app

    client = TestClient(app)

    payload = {
        "command": "notion_write",
        "intent": "batch_request",
        "params": {
            "operations": [
                {
                    "op_id": "g1",
                    "intent": "create_goal",
                    "payload": {
                        "title": "Goal 1",
                        "level": "Central",
                    },
                },
                {
                    "op_id": "g2",
                    "intent": "create_goal",
                    "payload": {
                        "title": "Goal 2",
                        "level": "Goal",
                    },
                },
            ]
        },
        "metadata": {"wrapper": {"prompt": "create 2 goals"}},
        # enterprise path expects patches key to exist (can be empty)
        "patches": [],
    }

    r = client.post(
        "/api/execute/preview", json=payload, headers={"X-Initiator": "ceo_chat"}
    )
    assert r.status_code == 200
    data = r.json()

    notion = data.get("notion")
    assert isinstance(notion, dict)
    assert notion.get("type") == "batch_preview"

    v = notion.get("validation")
    assert isinstance(v, dict)
    assert v.get("has_blockers") is True
    assert v.get("can_approve") is False

    rows = notion.get("rows")
    assert isinstance(rows, list) and rows

    row1 = next(
        (x for x in rows if isinstance(x, dict) and x.get("op_id") == "g1"), None
    )
    assert isinstance(row1, dict)
    rv = row1.get("validation")
    assert isinstance(rv, dict)
    issues = rv.get("issues")
    assert isinstance(issues, list)

    it = _find_issue_for_op(issues, op_id="g1", field="Level", code="invalid_option")
    assert isinstance(it, dict)
    allowed = it.get("allowed_values")
    assert isinstance(allowed, list)
    assert "Goal" in allowed
    assert "Outcome" in allowed


def test_preview_patches_fix_invalid_level_clears_blockers():
    from gateway.gateway_server import app

    client = TestClient(app)

    base = {
        "command": "notion_write",
        "intent": "batch_request",
        "params": {
            "operations": [
                {
                    "op_id": "g1",
                    "intent": "create_goal",
                    "payload": {
                        "title": "Goal 1",
                        "level": "Central",
                    },
                }
            ]
        },
        "metadata": {"wrapper": {"prompt": "create goal"}},
    }

    # Without patch -> blocked
    r0 = client.post(
        "/api/execute/preview",
        json={**base, "patches": []},
        headers={"X-Initiator": "ceo_chat"},
    )
    assert r0.status_code == 200
    notion0 = r0.json().get("notion")
    assert notion0["validation"]["has_blockers"] is True
    assert notion0["validation"]["can_approve"] is False

    # With patch -> unblocked
    r1 = client.post(
        "/api/execute/preview",
        json={
            **base,
            "patches": [{"op_id": "g1", "changes": {"Level": "Goal"}}],
        },
        headers={"X-Initiator": "ceo_chat"},
    )
    assert r1.status_code == 200
    notion1 = r1.json().get("notion")
    assert notion1["validation"]["has_blockers"] is False
    assert notion1["validation"]["can_approve"] is True
