from pathlib import Path

path = Path("gateway/gateway_server.py")
src = path.read_text(encoding="utf-8")

anchor = "def _inject_fallback_proposed_commands("
if anchor not in src:
    raise SystemExit("ANCHOR NOT FOUND")

lines = src.splitlines()
out = []
inside = False

for line in lines:
    out.append(line)

    if line.startswith(anchor):
        inside = True

    if inside and "pc = {" in line:
        out.append("            pc.setdefault('args', {})")
        out.append(
            "            if 'prompt' not in pc['args'] or not isinstance(pc['args'].get('prompt'), str):"
        )
        out.append("                pc['args']['prompt'] = prompt")

    if inside and line.strip().startswith("return"):
        inside = False

path.write_text("\n".join(out), encoding="utf-8")
print("OK — args.prompt enforced at fallback creation")
