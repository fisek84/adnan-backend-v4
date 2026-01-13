from pathlib import Path

p = Path("routers/chat_router.py")
s = p.read_text(encoding="utf-8")

anchor = "from services.ceo_advisor_agent import create_ceo_advisor_agent"
if anchor not in s:
    raise SystemExit("ANCHOR_NOT_FOUND:create_ceo_advisor_agent_import")

imp = "from dependencies import get_memory_read_only_service"
if imp not in s:
    s = s.replace(anchor, anchor + "\n" + imp)

old = "out = await create_ceo_advisor_agent(payload, {})"
new = (
    "mem_ro = get_memory_read_only_service()\n"
    "        mem_snapshot = mem_ro.export_public_snapshot() if mem_ro else {}\n"
    "        out = await create_ceo_advisor_agent(payload, {'memory': mem_snapshot})"
)

if old in s and new not in s:
    s = s.replace(old, new)

p.write_text(s, encoding="utf-8")
print("OK:patched routers/chat_router.py")
