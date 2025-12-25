# tests/test_canonical_chat_read_only.py
import requests

BASE = "http://127.0.0.1:8000"


def _discover_pending_endpoint() -> str:
    o = requests.get(f"{BASE}/openapi.json", timeout=10).json()
    paths = o.get("paths", {})
    candidates = [
        "/api/ai-ops/approval/pending",
        "/api/ai/ops/approval/pending",
        "/api/ai/ops/approvals/pending",
        "/api/ai/ops/approval/pending",
    ]
    for c in candidates:
        if c in paths:
            return c
    # fallback: find anything ending in approval/pending or approvals/pending
    for p in sorted(paths.keys()):
        if p.endswith("/approval/pending") or p.endswith("/approvals/pending"):
            return p
    raise RuntimeError("No approval pending endpoint found in OpenAPI")


def _pending_count(pending_path: str) -> int:
    r = requests.get(f"{BASE}{pending_path}", timeout=60)
    j = r.json()
    # support multiple shapes
    if "approvals" in j and isinstance(j["approvals"], list):
        return len(j["approvals"])
    if "items" in j and isinstance(j["items"], list):
        return len(j["items"])
    if "count" in j and isinstance(j["count"], int):
        return j["count"]
    return 0


def test_chat_is_read_only_and_does_not_create_approvals():
    pending_path = _discover_pending_endpoint()

    before = _pending_count(pending_path)

    payload = {"message": "create goal Test (chat should propose only)"}
    r = requests.post(f"{BASE}/api/chat", json=payload, timeout=20)
    r.raise_for_status()
    j = r.json()

    assert j.get("read_only") is True
    assert j.get("agent_id")
    assert isinstance(j.get("proposed_commands", []), list)

    after = _pending_count(pending_path)

    # chat must NOT create approvals by itself
    assert after == before
