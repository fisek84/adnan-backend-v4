from pathlib import Path

path = Path("routers/chat_router.py")
src = path.read_text(encoding="utf-8")

anchor = "proposed_commands.append({"
if anchor not in src:
    raise SystemExit("ANCHOR NOT FOUND in chat_router.py")

lines = src.splitlines()
out = []

inside = False
added = False

for line in lines:
    out.append(line)

    if anchor in line:
        inside = True
        added = False

    # Ako je args već prisutan u tom blocku, ne dodaj ništa
    if inside and "'args':" in line:
        added = True

    # Dodaj args odmah nakon command linije, ali samo ako još nije dodan
    if inside and (not added) and ("'command': 'ceo.command.propose'" in line):
        out.append("        'args': {'prompt': message},")
        added = True

    # Kraj bloka append({ ... })
    if inside and line.strip().endswith("})"):
        inside = False

path.write_text("\n".join(out) + "\n", encoding="utf-8")
print("OK — args.prompt enforced in /api/chat proposed_commands")
