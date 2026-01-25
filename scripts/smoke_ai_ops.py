import json
import requests

BASE = "http://127.0.0.1:8000"


def post(path, body):
    r = requests.post(BASE + path, json=body, timeout=20)
    return r.status_code, r.text


def get(path):
    r = requests.get(BASE + path, timeout=20)
    return r.status_code, r.text


print("health:", get("/health"))

st, res_txt = post(
    "/api/execute/raw",
    {
        "command": "ceo.command.propose",
        "intent": "ceo.command.propose",
        "params": {"prompt": "kreiraj task u notionu test idempotency"},
        "initiator": "ceo",
        "metadata": {"source": "smoke_script"},
    },
)
print("execute/raw:", st, res_txt)

res = json.loads(res_txt)
approval_id = res.get("approval_id")
if not approval_id:
    raise SystemExit("missing approval_id")

print("pending:", get("/api/ai-ops/approval/pending"))

st1, a1 = post(
    "/api/ai-ops/approval/approve",
    {"approval_id": approval_id, "approved_by": "smoke", "note": "first"},
)
print("approve #1:", st1, a1)

st2, a2 = post(
    "/api/ai-ops/approval/approve",
    {"approval_id": approval_id, "approved_by": "smoke", "note": "second"},
)
print("approve #2:", st2, a2)
