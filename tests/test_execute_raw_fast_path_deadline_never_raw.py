from __future__ import annotations

import json

from fastapi.testclient import TestClient

from models.canon import PROPOSAL_WRAPPER_INTENT


def _get_app():
    from gateway.gateway_server import app  # noqa: PLC0415

    return app


def _post_execute_raw_fast_path(prompt: str, *, intent_hint: str) -> dict:
    app = _get_app()
    client = TestClient(app)

    r = client.post(
        "/api/execute/raw",
        json={
            "command": PROPOSAL_WRAPPER_INTENT,
            "intent": PROPOSAL_WRAPPER_INTENT,
            "initiator": "ceo_chat",
            "params": {
                "prompt": prompt,
                "intent_hint": intent_hint,
                "type": intent_hint.replace("create_", ""),
            },
            "metadata": {"source": "pytest"},
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()

    cmd = body.get("command")
    assert isinstance(cmd, dict)
    md = cmd.get("metadata") or {}
    assert isinstance(md, dict)
    assert md.get("canon") == "execute_raw_unwrap_intent_hint_fast_path"

    return body


def _assert_no_raw_substring(body: dict, raw_date: str) -> None:
    blob = json.dumps(body.get("command") or body, ensure_ascii=False)
    assert raw_date not in blob


def test_fast_path_deadline_03_04_2026_never_forwarded_raw() -> None:
    prompt = (
        "Kreiraj cilj: Preseli se u EU za 30 dana.\n"
        "Deadline 03.04.2026\n"
        "Priority high"
    )

    body = _post_execute_raw_fast_path(prompt, intent_hint="create_goal")

    cmd = body["command"]
    params = cmd.get("params") or {}
    assert isinstance(params, dict)

    if "deadline" in params:
        assert params["deadline"] == "2026-04-03"

    _assert_no_raw_substring(body, "03.04.2026")


def test_fast_path_deadline_3_3_26_becomes_iso_or_omitted_never_raw() -> None:
    prompt = "Kreiraj cilj: Test cilj. Deadline 3.3.26, Status active"
    body = _post_execute_raw_fast_path(prompt, intent_hint="create_goal")

    cmd = body["command"]
    params = cmd.get("params") or {}
    assert isinstance(params, dict)

    # DD.MM.YY is deterministic: 3.3.26 -> 2026-03-03
    assert params.get("deadline") == "2026-03-03"
    _assert_no_raw_substring(body, "3.3.26")


def test_fast_path_invalid_deadline_is_omitted_and_never_raw() -> None:
    prompt = "Kreiraj cilj: Bad date. Deadline 31.02.2026, Priority high"
    body = _post_execute_raw_fast_path(prompt, intent_hint="create_goal")

    cmd = body["command"]
    params = cmd.get("params") or {}
    assert isinstance(params, dict)

    assert "deadline" not in params
    _assert_no_raw_substring(body, "31.02.2026")
