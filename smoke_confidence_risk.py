from fastapi.testclient import TestClient
from gateway.gateway_server import app

c = TestClient(app)

# 1) health/status
r = c.get("/health")
assert r.status_code == 200 and r.json().get("status") == "ok"

r = c.get("/api/ceo-console/status")
assert r.status_code == 200 and r.json().get("read_only") is True

# 2) ai/run read-only + proposals list
r0 = c.post("/api/ai/run", json={})
assert r0.status_code in (400, 422)

r = c.post(
    "/api/ai/run",
    json={"text": "napravi cilj test cilj, prioritet High, status Active"},
)
assert r.status_code == 200
body = r.json()

assert body.get("ok") is True
assert body.get("read_only") is True
assert isinstance(body.get("proposed_commands"), list)

# 3) confidence_risk in meta
meta = body.get("meta") if isinstance(body.get("meta"), dict) else {}
cr = meta.get("confidence_risk")

assert isinstance(cr, dict), f"confidence_risk missing. meta_keys={list(meta.keys())}"
assert "confidence" in cr and "risk" in cr, f"confidence_risk invalid shape: {cr}"

print("OK: smoke test passed. confidence_risk=", cr)
